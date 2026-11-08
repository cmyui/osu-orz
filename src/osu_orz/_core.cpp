// nanobind bindings for the ORZ codec (extern/osu_replay_zip), on bytes

#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>

#include <charconv>
#include <cstring>
#include <span>
#include <stdexcept>
#include <vector>

#include "orz_shared.h"
#include "orz_write.h"
#include "orz_read.h"

namespace nb = nanobind;

using namespace orz;

namespace {

	struct orz_error : std::runtime_error {
		using std::runtime_error::runtime_error;
	};

	// bytes are immutable and the caller holds them, so the span stays valid with the GIL released
	std::span<const u8> view(const nb::bytes& b) {
		return { (const u8*)b.c_str(), b.size() };
	}

	nb::bytes to_bytes(const std::vector<u8>& v) {
		return nb::bytes((const char*)v.data(), v.size());
	}

	bool is_orz(std::span<const u8> data) {
		return !data.empty() && data[0] == ORZ_MAGIC;
	}

	// an .osr starts with its game mode, then the osu! version that wrote it
	bool looks_like_osr(std::span<const u8> data) {

		if (data.size() < 5 || data[0] > 3)
			return false;

		u32 version;

		memcpy(&version, data.data() + 1, 4);

		return version >= 20070000 && version <= 30070000;
	}

	// all of data, and nothing past it, is one device
	bool read_device(std::span<const u8> data, dspace::_model_info& m) {

		_bit_view in{ data };

		return dspace::read_info(in, m) && in.in <= in.max_size() && in.get_tail().empty();
	}

	// some axis has a device model: its positions are not only text
	bool has_device(const dspace::_model_info& m) {

		for (const auto& axis : m.axis)
			for (const auto& s : axis.seg)
				if (s.p.device.kind != dspace::axis_mode::none && s.p.device.kind != dspace::axis_mode::text)
					return true;

		return false;
	}

	// a device as .orz files store it, None when no axis has a device model
	nb::object device_bytes(const dspace::_model_info& m) {

		if (!has_device(m))
			return nb::none();

		bit_stream o{};

		dspace::write_info(m, o);

		return to_bytes(o.data);
	}

	// the first hint whose device (each axis's last segment) the output is coded with, -1 for none. A mouse's poll rate
	// may differ: the encoder picks the one that codes the replay best
	int matched_hint(const dspace::_model_info& device, std::span<const dspace::_model_info> hints) {

		if (!has_device(device))
			return -1;

		for (size_t i{}; i < hints.size(); ++i) {

			const auto same = [&](int a) {

				const auto& got{ device.axis[a].seg };
				const auto& hint{ hints[i].axis[a].seg };

				if (got.size() != 1 || hint.empty())
					return false;

				auto p{ hint.back().p };
				p.device.mouse.poll = got[0].p.device.mouse.poll;

				return p == got[0].p;
			};

			if (same(0) && same(1))
				return (int)i;

		}

		return -1;
	}

	// how the output's frames are coded, as osu_orz.Coding numbers them
	int coding_of(u32 encode_info, const dspace::_model_info& device) {

		if (encode_info & ORZ_ENCODE_INFO::replay_verbatim)
			return 0;

		const e_mode mode{ get_e_mode(encode_info) };

		if (uses_modes_coder(mode))
			return 1;

		if (mode == e_mode::osu_autopilot)
			return 4;

		return has_device(device) ? 3 : 2;
	}

	// runs to_orz(out, state) with the GIL released, and gives back (orz, device, matched hint, coding). check_round_trip:
	// the encoder decodes what it wrote, and stores the replay data as it is when that does not give the replay back
	template <class F>
	nb::tuple encode(F to_orz, bool check_round_trip, const std::vector<nb::bytes>& device_hints, const char* failure) {

		std::vector<dspace::_model_info> hints(device_hints.size());

		for (size_t i{}; i < hints.size(); ++i)
			if (!read_device(view(device_hints[i]), hints[i]))
				throw orz_error("a device hint is not a device");

		std::vector<u8> out;
		orz_state state{};
		bool ok;

		{
			nb::gil_scoped_release release;

			state.options = check_round_trip ? ENCODE_CHECK_ROUND_TRIP : 0;
			state.hints.devices = hints;

			ok = to_orz(out, state);
		}

		if (!ok)
			throw orz_error(failure);

		const int hint{ matched_hint(state.device, hints) };

		return nb::make_tuple(to_bytes(out), device_bytes(state.device), hint < 0 ? nb::none() : nb::object(nb::int_(hint)),
			coding_of(state.file.encode_info, state.device));
	}

	nb::tuple compress_osr(const nb::bytes& data, bool check_round_trip, const std::vector<nb::bytes>& device_hints) {

		const auto input{ view(data) };

		if (is_orz(input))
			throw orz_error("already an .orz file");

		if (_osr_header h{}; !read_osr_header(input, h))
			throw orz_error("not an .osr file (bare replay data needs a mode)");

		return encode([&](auto& out, auto& state) { return osr_to_orz(input, out, state); }, check_round_trip, device_hints,
			"could not compress this replay");
	}

	// mode: the e_mode, 0 to 6 (finding autopilot is the encoder's job)
	nb::tuple compress_replay_data(const nb::bytes& data, u32 mode, bool check_round_trip,
		const std::vector<nb::bytes>& device_hints) {

		const auto input{ view(data) };

		if (is_orz(input))
			throw orz_error("already an .orz file");

		if (looks_like_osr(input))
			throw orz_error("an .osr says its own mode; give a mode only with bare replay data");

		return encode([&](auto& out, auto& state) { return replay_data_to_orz(input, (e_mode)mode, out, state); },
			check_round_trip, device_hints, "could not compress this replay data");
	}

	// skip_crc: give back what the file decodes to even when it fails its CRC check
	nb::bytes decompress(const nb::bytes& data, bool skip_crc) {

		const auto input{ view(data) };

		std::vector<u8> out;
		bool ok, damaged{};

		{
			nb::gil_scoped_release release;

			ok = orz_to_osr(input, out, skip_crc ? DECODE_SKIP_CRC : 0);

			// a file that only fails its CRC is damaged, or from an incompatible build
			if (!ok && !skip_crc && !is_newer_orz(input)) {

				_decoded_orz d;

				damaged = orz_decode_frames(input, d, DECODE_SKIP_CRC);

			}
		}

		if (!ok) {

			if (is_newer_orz(input))
				throw orz_error("made by a newer version of the ORZ format");

			throw orz_error(damaged ? "fails its CRC check (damaged, or written by an incompatible build)" : "not a valid .orz file");
		}

		return to_bytes(out);
	}

	// the shortest decimal that reads back as f, so 1.6f reads 1.6 and not 1.600000023841858
	double readable(float f) {

		char text[32];
		double d{};

		std::from_chars(text, std::to_chars(text, text + sizeof text, f).ptr, d);

		return d;
	}

	// a device's segments for one axis, each with only the parameters its kind has
	nb::list axis_segments(const dspace::axis_model& axis) {

		using namespace dspace;

		nb::list out;

		for (const auto& s : axis.seg) {

			const auto& p{ s.p };

			nb::dict d;

			d["start"] = s.start;
			d["kind"] = (int)p.device.kind;

			if (p.device.kind == axis_mode::rational)
				d["rational"] = nb::make_tuple(p.device.rational.a, p.device.rational.b, p.device.rational.D);

			if (p.device.kind == axis_mode::mouse) {
				d["sensitivity"] = readable(p.device.mouse.sens);
				d["poll_rate"] = readable(p.device.mouse.poll);
			}

			if (p.device.kind == axis_mode::absolute) {
				d["mapping"] = p.device.absolute.mapping == tablet_mapping::window ? "window" : "desktop";
				d["span"] = readable(p.device.absolute.span);
				d["speed"] = readable(p.device.absolute.speed);
				d["window_half"] = readable(p.game.window_half);
				d["origin"] = readable(p.game.origin);
				d["x87"] = p.game.fp == float_unit::x87;
			}

			if (p.device.kind == axis_mode::mouse || p.device.kind == axis_mode::absolute) {
				d["scale"] = readable(p.game.scale);
				d["offset"] = readable(p.game.off);
				d["unrounded_sub"] = p.game.unrounded_sub;
			}

			out.append(d);

		}

		return out;
	}

	nb::tuple device_segments(const nb::bytes& data) {

		dspace::_model_info m{};

		if (!read_device(view(data), m))
			throw orz_error("not a device");

		return nb::make_tuple(axis_segments(m.axis[0]), axis_segments(m.axis[1]));
	}

	// the device an .orz's frames are coded with, empty when osu!standard's coder did not code them. Reads only the
	// file's head: the frames are not decoded, so the CRC is not checked
	bool read_orz_device(std::span<const u8> input, dspace::_model_info& m) {

		_orz_file file{};

		if (!file.decode(input))
			return false;

		const u32 info{ file.encode_info };
		const e_mode mode{ get_e_mode(info) };

		if (mode >= e_mode::e_mode_max)
			return false;

		if ((info & ORZ_ENCODE_INFO::replay_verbatim) || uses_modes_coder(mode))
			return true;

		standard::_frames_head head{};

		if (!standard::read_head(container_data(file, orz_tag::frames), mode == e_mode::osu_autopilot, head))
			return false;

		m = std::move(head.info);

		return true;
	}

	nb::object orz_device(const nb::bytes& data) {

		const auto input{ view(data) };

		dspace::_model_info m{};
		bool ok;

		{
			nb::gil_scoped_release release;

			try {
				ok = read_orz_device(input, m);
			} catch (const std::exception&) {
				ok = false;
			}
		}

		if (!ok)
			throw orz_error(is_newer_orz(input) ? "made by a newer version of the ORZ format" : "not a valid .orz file");

		return device_bytes(m);
	}

}

NB_MODULE(_core, m) {

	nb::exception<orz_error>(m, "OrzError", PyExc_ValueError);

	m.attr("FORMAT_VERSION") = ORZ_VERSION;

	m.def("compress_osr", &compress_osr, nb::arg("data"), nb::arg("check_round_trip"), nb::arg("device_hints"));
	m.def("compress_replay_data", &compress_replay_data, nb::arg("data"), nb::arg("mode"), nb::arg("check_round_trip"),
		nb::arg("device_hints"));
	m.def("decompress", &decompress, nb::arg("data"), nb::arg("skip_crc"));
	m.def("device_segments", &device_segments, nb::arg("data"));
	m.def("orz_device", &orz_device, nb::arg("data"));
}
