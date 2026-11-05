// nanobind bindings for the ORZ codec (extern/osu_replay_zip), on bytes

#include <nanobind/nanobind.h>

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

	// runs to_orz(out, state) with the GIL released. check_round_trip: the encoder decodes what it wrote, and stores the
	// replay data as it is when that does not give the replay back
	template <class F>
	nb::bytes encode(F to_orz, bool check_round_trip, const char* failure) {

		std::vector<u8> out;
		bool ok;

		{
			nb::gil_scoped_release release;

			orz_state state{};
			state.options = check_round_trip ? ENCODE_CHECK_ROUND_TRIP : 0;

			ok = to_orz(out, state);
		}

		if (!ok)
			throw orz_error(failure);

		return to_bytes(out);
	}

	nb::bytes compress_osr(const nb::bytes& data, bool check_round_trip) {

		const auto input{ view(data) };

		if (is_orz(input))
			throw orz_error("already an .orz file");

		if (_osr_header h{}; !read_osr_header(input, h))
			throw orz_error("not an .osr file (bare replay data needs a mode)");

		return encode([&](auto& out, auto& state) { return osr_to_orz(input, out, state); }, check_round_trip,
			"could not compress this replay");
	}

	// mode: the e_mode, 0 to 6 (finding autopilot is the encoder's job)
	nb::bytes compress_replay_data(const nb::bytes& data, u32 mode, bool check_round_trip) {

		const auto input{ view(data) };

		if (is_orz(input))
			throw orz_error("already an .orz file");

		if (looks_like_osr(input))
			throw orz_error("an .osr says its own mode; give a mode only with bare replay data");

		return encode([&](auto& out, auto& state) { return replay_data_to_orz(input, (e_mode)mode, out, state); },
			check_round_trip, "could not compress this replay data");
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

}

NB_MODULE(_core, m) {

	nb::exception<orz_error>(m, "OrzError", PyExc_ValueError);

	m.attr("FORMAT_VERSION") = ORZ_VERSION;

	m.def("compress_osr", &compress_osr, nb::arg("data"), nb::arg("check_round_trip"));
	m.def("compress_replay_data", &compress_replay_data, nb::arg("data"), nb::arg("mode"), nb::arg("check_round_trip"));
	m.def("decompress", &decompress, nb::arg("data"), nb::arg("skip_crc"));
}
