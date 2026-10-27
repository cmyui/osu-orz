// How well the priors this is built with compress replays: reads frames_prior_gen's stdin records (an e_mode byte, or 255
// for an .osr, the size in 4 bytes, then the bytes), encodes each, and prints the replays encoded, their bytes and their
// encoded bytes. Replays the encoder can not handle are left out of all three.

#include <cstdio>
#include <vector>

#include "orz_shared.h"
#include "orz_write.h"
#include "orz_read.h"

using namespace orz;

int main() {

	size_t replays{}, bytes{}, encoded_bytes{};
	std::vector<u8> data, encoded;

	for (u8 mode; fread(&mode, 1, 1, stdin) == 1;) {

		u32 size;

		if (fread(&size, sizeof size, 1, stdin) != 1)
			return 1;

		data.resize(size);

		if (fread(data.data(), 1, size, stdin) != size)
			return 1;

		orz_state state{};

		const bool ok{ mode == 255 ? osr_to_orz(data, encoded, state) : replay_data_to_orz(data, (e_mode)mode, encoded, state) };

		if (!ok)
			continue;

		++replays;
		bytes += size;
		encoded_bytes += encoded.size();

	}

	printf("%zu\t%zu\t%zu\n", replays, bytes, encoded_bytes);

	return 0;
}
