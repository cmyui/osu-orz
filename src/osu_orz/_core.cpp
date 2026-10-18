// nanobind bindings for the ORZ codec (extern/osu_replay_zip), on bytes

#include <nanobind/nanobind.h>

#include <stdexcept>
#include <string>
#include <vector>

#include "orz_shared.h"
#include "orz_write.h"
#include "orz_read.h"

namespace nb = nanobind;

namespace {

	struct orz_error : std::runtime_error {
		using std::runtime_error::runtime_error;
	};

	std::vector<u8> to_vector(const nb::bytes& b) {

		const auto* p{ (const u8*)b.c_str() };

		return { p, p + b.size() };
	}

	nb::bytes to_bytes(const std::vector<u8>& v) {
		return nb::bytes((const char*)v.data(), v.size());
	}

	// info: 0 for an .osr file, or what bare replay data is (header_info())
	nb::bytes compress(const nb::bytes& data, u32 info) {

		const auto input{ to_vector(data) };

		orz_state state{};

		{
			nb::gil_scoped_release release;

			osr_to_orz(input, info, state);
		}

		if (state.output.empty())
			throw orz_error(state.error);

		return to_bytes(state.output);
	}

	nb::bytes decompress(const nb::bytes& data) {

		const auto input{ to_vector(data) };

		std::vector<u8> out;
		bool ok, damaged{};

		{
			nb::gil_scoped_release release;

			ok = orz_to_osr(input, out);

			// a file that only fails its CRC is damaged, or from an incompatible build
			if (!ok && !read_container(input).newer) {

				_decoded_orz d;

				damaged = orz_decode_frames(input, d, DECODE_SKIP_CRC);

			}
		}

		if (!ok) {

			if (read_container(input).newer)
				throw orz_error("made by a newer version of the ORZ format");

			throw orz_error(damaged ? "fails its CRC check (damaged, or written by an incompatible build)" : "not a valid .orz file");
		}

		return to_bytes(out);
	}

}

NB_MODULE(_core, m) {

	nb::exception<orz_error>(m, "OrzError", PyExc_ValueError);

	m.attr("FORMAT_VERSION") = ORZ_VERSION;

	m.def("compress", &compress, nb::arg("data"), nb::arg("info"));
	m.def("header_info", &header_info, nb::arg("mode"), nb::arg("relax"));
	m.def("decompress", &decompress, nb::arg("data"));
}
