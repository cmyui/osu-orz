// nanobind bindings for the ORZ codec (extern/osu_replay_zip), on bytes

#include <nanobind/nanobind.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/variant.h>
#include <nanobind/stl/vector.h>

#include <charconv>
#include <cstring>
#include <initializer_list>
#include <optional>
#include <span>
#include <stdexcept>
#include <string>
#include <variant>
#include <vector>

#include "orz_shared.h"
#include "orz_write.h"
#include "orz_read.h"

namespace nb = nanobind;

using namespace orz;

// The types Python gets. The codec keeps a device model as one struct with every kind's parameters, its kind saying
// which hold (dspace::axis_params); here each kind is its own type with only its own parameters. Floats are the
// codec's float32s, each as the shortest decimal that reads back as it.
namespace py {

	enum class coding { verbatim, taiko_catch_mania, text, device, autopilot };

	enum class mapping { window, desktop };

	struct playfield {
		double scale, offset;
		bool unrounded_sub;
	};

	struct rational {
		int a, b, d;
	};

	struct mouse {
		double sensitivity, poll_rate;
		py::playfield playfield;
	};

	struct absolute {
		py::mapping mapping;
		double span, speed, window_half, origin;
		bool x87;
		py::playfield playfield;
	};

	struct text {};

	struct axis_segment {
		u32 start;
		std::variant<rational, mouse, absolute, text> model;
	};

	using segments = nb::typed<nb::tuple, axis_segment, nb::ellipsis>;

	struct device {
		nb::bytes data;
		segments x, y;
	};

	struct compress_result {
		nb::bytes compressed_bytes;
		std::optional<py::device> device;
		std::optional<int> hint_used;
		py::coding coding;
	};

}

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

	// the shortest decimal that reads back as f, so 1.6f reads 1.6 and not 1.600000023841858
	double readable(float f) {

		char text[32];
		double d{};

		std::from_chars(text, std::to_chars(text, text + sizeof text, f).ptr, d);

		return d;
	}

	py::playfield playfield_of(const dspace::_game_state_model& g) {
		return { readable(g.scale), readable(g.off), g.unrounded_sub };
	}

	// the codec reads axis_mode::none too, but its encoder never writes it: none marks what detection could not fit,
	// which is written as text
	std::vector<py::axis_segment> segments_of(const dspace::axis_model& axis) {

		using dspace::axis_mode;

		std::vector<py::axis_segment> out;

		for (const auto& s : axis.seg) {

			const auto& d{ s.p.device };
			const auto& g{ s.p.game };

			switch (d.kind) {
			case axis_mode::rational:
				out.push_back({ s.start, py::rational{ d.rational.a, d.rational.b, d.rational.D } });
				break;
			case axis_mode::mouse:
				out.push_back({ s.start, py::mouse{ readable(d.mouse.sens), readable(d.mouse.poll), playfield_of(g) } });
				break;
			case axis_mode::absolute:
				out.push_back({ s.start, py::absolute{
					d.absolute.mapping == dspace::tablet_mapping::window ? py::mapping::window : py::mapping::desktop,
					readable(d.absolute.span), readable(d.absolute.speed), readable(g.window_half), readable(g.origin),
					g.fp == dspace::float_unit::x87, playfield_of(g) } });
				break;
			case axis_mode::text:
				out.push_back({ s.start, py::text{} });
				break;
			default:
				throw orz_error("not a device");
			}
		}

		return out;
	}

	// some axis has a device model: its positions are not only text
	bool has_device(const dspace::_model_info& m) {

		for (const auto& axis : m.axis)
			for (const auto& s : axis.seg)
				if (s.p.device.kind != dspace::axis_mode::none && s.p.device.kind != dspace::axis_mode::text)
					return true;

		return false;
	}

	py::device to_device(const dspace::_model_info& m) {

		bit_stream o{};

		dspace::write_info(m, o);

		const auto axis = [&](int a) { return nb::borrow<py::segments>(nb::tuple(nb::cast(segments_of(m.axis[a])))); };

		return { to_bytes(o.data), axis(0), axis(1) };
	}

	// none when no axis has a device model
	std::optional<py::device> device_of(const dspace::_model_info& m) {

		if (!has_device(m))
			return {};

		return to_device(m);
	}

	// all of data, and nothing past it, is one device. dspace::read_info reads a device inside a bit stream; data is
	// write_info's bits on their own, padded to a byte, which only this binding hands out
	bool read_device(std::span<const u8> data, dspace::_model_info& m) {

		_bit_view in{ data };

		return dspace::read_info(in, m) && in.in <= in.max_size() && in.get_tail().empty();
	}

	py::device device_from_bytes(const nb::bytes& data) {

		dspace::_model_info m{};

		if (!read_device(view(data), m))
			throw orz_error("not a device");

		return to_device(m);
	}

	py::coding coding_of(u32 encode_info, const dspace::_model_info& device) {

		if (encode_info & ORZ_ENCODE_INFO::replay_verbatim)
			return py::coding::verbatim;

		const e_mode mode{ get_e_mode(encode_info) };

		if (uses_modes_coder(mode))
			return py::coding::taiko_catch_mania;

		if (mode == e_mode::osu_autopilot)
			return py::coding::autopilot;

		return has_device(device) ? py::coding::device : py::coding::text;
	}

	// runs to_orz(out, state) with the GIL released. check_round_trip: the encoder decodes what it wrote, and stores the
	// replay data as it is when that does not give the replay back
	template <class F>
	py::compress_result encode(F to_orz, bool check_round_trip, const std::vector<nb::bytes>& device_hints,
		const char* failure) {

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

		return { to_bytes(out), device_of(state.device),
			state.device_hint >= 0 ? std::optional<int>{ state.device_hint } : std::nullopt,
			coding_of(state.file.encode_info, state.device) };
	}

	py::compress_result compress_osr(const nb::bytes& data, bool check_round_trip,
		const std::vector<nb::bytes>& device_hints) {

		const auto input{ view(data) };

		if (is_orz(input))
			throw orz_error("already an .orz file");

		if (_osr_header h{}; !read_osr_header(input, h))
			throw orz_error("not an .osr file (bare replay data needs a mode)");

		return encode([&](auto& out, auto& state) { return osr_to_orz(input, out, state); }, check_round_trip, device_hints,
			"could not compress this replay");
	}

	// mode: the e_mode, 0 to 6 (finding autopilot is the encoder's job)
	py::compress_result compress_replay_data(const nb::bytes& data, u32 mode, bool check_round_trip,
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

	std::optional<py::device> orz_device(const nb::bytes& data) {

		const auto input{ view(data) };

		dspace::_model_info m{};
		bool ok;

		{
			nb::gil_scoped_release release;

			ok = orz_read_device(input, m);
		}

		if (!ok)
			throw orz_error(is_newer_orz(input) ? "made by a newer version of the ORZ format" : "not a valid .orz file");

		return device_of(m);
	}

	// a read-only value type with these fields: equal to another with equal fields, and hashed and shown by them
	template <class T>
	nb::class_<T> value_class(nb::module_& m, const char* name, const char* doc, std::initializer_list<const char*> names) {

		const std::vector<const char*> fields(names);

		const auto values = [fields](nb::handle self) {

			nb::list out;

			for (auto f : fields)
				out.append(self.attr(f));

			return nb::tuple(out);
		};

		nb::class_<T> c(m, name, doc);

		c.def("__eq__", [values](nb::handle a, nb::handle b) { return a.type().is(b.type()) && values(a).equal(values(b)); },
			nb::sig("def __eq__(self, other: object, /) -> bool"));
		c.def("__hash__", [values](nb::handle self) { return nb::hash(values(self)); });
		c.def("__repr__", [name, fields, values](nb::handle self) {

			const auto v{ values(self) };
			std::string text{ std::string(name) + "(" };

			for (size_t i{}; i < fields.size(); ++i)
				text += (i ? ", " : "") + std::string(fields[i]) + "=" + nb::cast<std::string>(nb::repr(v[i]));

			return text + ")";
		});

		return c;
	}

}

NB_MODULE(_core, m) {

	nb::exception<orz_error>(m, "OrzError", PyExc_ValueError);

	m.attr("FORMAT_VERSION") = ORZ_VERSION;

	nb::enum_<py::coding>(m, "Coding", nb::is_arithmetic(), "How an .orz codes its replay's frames.")
		.value("VERBATIM", py::coding::verbatim, "Not coded: the replay data is stored as it was given.")
		.value("TAIKO_CATCH_MANIA", py::coding::taiko_catch_mania,
			"The coder for osu!taiko, osu!taiko with Relax, osu!catch and osu!mania.")
		.value("TEXT", py::coding::text,
			"osu!standard's coder (osu!, and osu!catch with Relax), positions as their decimal text: no device model fit.")
		.value("DEVICE", py::coding::device, "osu!standard's coder, positions on a device model.")
		.value("AUTOPILOT", py::coding::autopilot,
			"osu!standard's coder, positions on the path osu!'s autopilot moves the cursor along.");

	nb::enum_<py::mapping>(m, "Mapping", "What a tablet or touch screen's area maps onto.")
		.value("WINDOW", py::mapping::window, "osu!'s window.")
		.value("DESKTOP", py::mapping::desktop, "The desktop.");

	value_class<py::playfield>(m, "Playfield",
		"Where the playfield sits in osu!'s window: a position of window pixels is (pixels - offset) / scale on the\n"
		"playfield.",
		{ "scale", "offset", "unrounded_sub" })
		.def_ro("scale", &py::playfield::scale, "Window pixels per playfield pixel.")
		.def_ro("offset", &py::playfield::offset, "The playfield's origin, in window pixels.")
		.def_ro("unrounded_sub", &py::playfield::unrounded_sub,
			"pixels - offset stays at full precision (osu! did it on the x87 unit) before the division.");

	value_class<py::rational>(m, "Rational",
		"Positions on the OS cursor's lattice, (a * k + b) / d for whole k: mostly raw input off, from any device.",
		{ "a", "b", "d" })
		.def_ro("a", &py::rational::a)
		.def_ro("b", &py::rational::b)
		.def_ro("d", &py::rational::d);

	value_class<py::mouse>(m, "Mouse",
		"A device that reports movement (a mouse, with raw input on): counts times sensitivity, polled poll_rate\n"
		"times a second.",
		{ "sensitivity", "poll_rate", "playfield" })
		.def_ro("sensitivity", &py::mouse::sensitivity)
		.def_ro("poll_rate", &py::mouse::poll_rate, "Reports a second.")
		.def_ro("playfield", &py::mouse::playfield);

	value_class<py::absolute>(m, "Absolute",
		"A device that reports where it points (a tablet or touch screen), mapped onto the window or the desktop.",
		{ "mapping", "span", "speed", "window_half", "origin", "x87", "playfield" })
		.def_ro("mapping", &py::absolute::mapping)
		.def_ro("span", &py::absolute::span, "The size of what the device maps onto, in pixels.")
		.def_ro("speed", &py::absolute::speed, "The speed setting.")
		.def_ro("window_half", &py::absolute::window_half, "Half the window's size, in pixels.")
		.def_ro("origin", &py::absolute::origin, "The window's origin relative to the screen's, in pixels.")
		.def_ro("x87", &py::absolute::x87, "osu! did the float maths on the x87 unit (else SSE).")
		.def_ro("playfield", &py::absolute::playfield);

	value_class<py::text>(m, "Text", "No model fit: positions as their decimal text.", {});

	value_class<py::axis_segment>(m, "AxisSegment",
		"One axis's device model from frame start on. start counts the frames whose position is coded, so frames\n"
		"that repeat the frame before them are not counted.",
		{ "start", "model" })
		.def_ro("start", &py::axis_segment::start)
		.def_ro("model", &py::axis_segment::model);

	value_class<py::device>(m, "Device",
		"The device model a replay's cursor positions are coded on, per axis.\n\n"
		"data is the device as .orz files store it: pass it, or the Device, to compress as a hint. It is tied to the\n"
		"format version that wrote it. x and y read it out: one segment per axis, or more when the setup changed during\n"
		"the replay (window moved, device swapped).",
		{ "data", "x", "y" })
		.def_ro("data", &py::device::data)
		.def_ro("x", &py::device::x)
		.def_ro("y", &py::device::y)
		.def_static("from_bytes", &device_from_bytes, nb::arg("data"),
			"Read a device's data. Raises OrzError when it is not one.");

	value_class<py::compress_result>(m, "CompressResult",
		"What compress made.\n\n"
		"device is None unless osu!standard's coder put some axis on a device model (coding is DEVICE). hint_used is\n"
		"the index of the hint the encoder took, skipping its own device search (a mouse's poll rate is picked again),\n"
		"None when it searched. A search can find a hint's device too: compare devices to tell whether a replay's is a\n"
		"hint's.",
		{ "compressed_bytes", "device", "hint_used", "coding" })
		.def_ro("compressed_bytes", &py::compress_result::compressed_bytes)
		.def_ro("device", &py::compress_result::device)
		.def_ro("hint_used", &py::compress_result::hint_used)
		.def_ro("coding", &py::compress_result::coding);

	m.def("compress_osr", &compress_osr, nb::arg("data"), nb::arg("check_round_trip"), nb::arg("device_hints"));
	m.def("compress_replay_data", &compress_replay_data, nb::arg("data"), nb::arg("mode"), nb::arg("check_round_trip"),
		nb::arg("device_hints"));
	m.def("decompress", &decompress, nb::arg("data"), nb::arg("skip_crc"));
	m.def("orz_device", &orz_device, nb::arg("data"));
}
