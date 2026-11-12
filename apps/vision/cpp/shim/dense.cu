// The detector's dense stage on the GPU: a sparse sample pyramid thresholded against local
// contrast and noise into one bit per sample. Must match `src/apriltag/dense.rs` bit for bit.
#include <cuda_runtime.h>

#include <cstdint>
#include <cstdio>
#include <new>

namespace {

constexpr int kTile = 4;
constexpr int kRegion = 8;  // tiles
constexpr int kPatch = 32;  // level-0 samples per block side
constexpr int kMaxLevels = 4;

struct Level {
  int width, height, words;
  int tiles_x, tiles_y;
  int regions_x, regions_y;
  uint8_t *data;
  uint8_t *tile_min, *tile_max, *tile_rough;
  uint32_t *mask;  // device
};

struct Params {
  int levels;
  int step, start;
  int min_contrast;
  int noise_factor;
  // Prefix sums of each level's region count, for mapping blocks to levels.
  int region_start[kMaxLevels + 1];
  Level level[kMaxLevels];
};

__device__ inline uint8_t average(uint8_t a, uint8_t b, uint8_t c, uint8_t d) {
  return static_cast<uint8_t>((a + b + c + d + 2) >> 2);
}

// One block per 32x32 patch of level-0 samples: samples every level inside the patch, then
// the min, max, and roughness of each tile inside it.
__global__ void sample_kernel(const uint8_t *gray, int pitch, Params p) {
  __shared__ uint8_t s0[32][32];
  __shared__ uint8_t s1[16][16];
  __shared__ uint8_t s2[8][8];
  __shared__ uint8_t s3[4][4];
  const int tx = threadIdx.x, ty = threadIdx.y;
  {
    const Level &l = p.level[0];
    const int x = blockIdx.x * 32 + tx, y = blockIdx.y * 32 + ty;
    uint8_t v = 0;
    if (x < l.width && y < l.height) {
      v = gray[static_cast<size_t>(p.start + y * p.step) * pitch + p.start + x * p.step];
      l.data[y * l.width + x] = v;
    }
    s0[ty][tx] = v;
  }
  __syncthreads();
  if (p.levels > 1 && tx < 16 && ty < 16) {
    const Level &l = p.level[1];
    const int x = blockIdx.x * 16 + tx, y = blockIdx.y * 16 + ty;
    const uint8_t v = average(s0[2 * ty][2 * tx], s0[2 * ty][2 * tx + 1], s0[2 * ty + 1][2 * tx],
                              s0[2 * ty + 1][2 * tx + 1]);
    s1[ty][tx] = v;
    if (x < l.width && y < l.height) l.data[y * l.width + x] = v;
  }
  __syncthreads();
  if (p.levels > 2 && tx < 8 && ty < 8) {
    const Level &l = p.level[2];
    const int x = blockIdx.x * 8 + tx, y = blockIdx.y * 8 + ty;
    const uint8_t v = average(s1[2 * ty][2 * tx], s1[2 * ty][2 * tx + 1], s1[2 * ty + 1][2 * tx],
                              s1[2 * ty + 1][2 * tx + 1]);
    s2[ty][tx] = v;
    if (x < l.width && y < l.height) l.data[y * l.width + x] = v;
  }
  __syncthreads();
  if (p.levels > 3 && tx < 4 && ty < 4) {
    const Level &l = p.level[3];
    const int x = blockIdx.x * 4 + tx, y = blockIdx.y * 4 + ty;
    const uint8_t v = average(s2[2 * ty][2 * tx], s2[2 * ty][2 * tx + 1], s2[2 * ty + 1][2 * tx],
                              s2[2 * ty + 1][2 * tx + 1]);
    s3[ty][tx] = v;
    if (x < l.width && y < l.height) l.data[y * l.width + x] = v;
  }
  __syncthreads();

  // Threads 0-63 take level 0's 8x8 tiles, 64-79 level 1's 4x4, 80-83 level 2's, 84 level 3's.
  int t = ty * 32 + tx;
  int k, per_side;
  if (t < 64) {
    k = 0, per_side = 8;
  } else if (t < 80) {
    k = 1, per_side = 4, t -= 64;
  } else if (t < 84) {
    k = 2, per_side = 2, t -= 80;
  } else if (t < 85) {
    k = 3, per_side = 1, t -= 84;
  } else {
    return;
  }
  if (k >= p.levels) return;
  const Level &l = p.level[k];
  const int i = t % per_side, j = t / per_side;
  const int tile_x = blockIdx.x * per_side + i, tile_y = blockIdx.y * per_side + j;
  if (tile_x >= l.tiles_x || tile_y >= l.tiles_y) return;
  int lo = 255, hi = 0, rough = 0;
  for (int dy = 0; dy < kTile; dy++) {
    const int sy = j * kTile + dy;
    if (tile_y * kTile + dy >= l.height) break;
    int previous = -1;
    for (int dx = 0; dx < kTile; dx++) {
      if (tile_x * kTile + dx >= l.width) break;
      const int sx = i * kTile + dx;
      const int v = k == 0 ? s0[sy][sx] : k == 1 ? s1[sy][sx] : k == 2 ? s2[sy][sx] : s3[sy][sx];
      lo = min(lo, v);
      hi = max(hi, v);
      if (previous >= 0) rough += abs(v - previous);
      previous = v;
    }
  }
  const int index = tile_y * l.tiles_x + tile_x;
  l.tile_min[index] = lo;
  l.tile_max[index] = hi;
  l.tile_rough[index] = min(rough / (kTile * (kTile - 1)), 255);
}

// One block per region of 8x8 tiles (32x32 samples) of any level: the region's noise floor,
// each tile's threshold, and the region's mask bits.
__global__ void mask_kernel(Params p) {
  __shared__ uint8_t rough[64];
  __shared__ uint8_t thresholds[64];
  __shared__ int quartile;
  int k = 0;
  while (k + 1 < p.levels && blockIdx.x >= p.region_start[k + 1]) k++;
  const Level &l = p.level[k];
  const int region = blockIdx.x - p.region_start[k];
  const int rx = region % l.regions_x, ry = region / l.regions_x;
  const int nx = min(kRegion, l.tiles_x - rx * kRegion), ny = min(kRegion, l.tiles_y - ry * kRegion);
  const int t = threadIdx.x;
  const int i = t % kRegion, j = t / kRegion;
  const bool tile = t < 64 && i < nx && j < ny;
  const int tile_x = rx * kRegion + i, tile_y = ry * kRegion + j;
  if (t < 64) rough[t] = tile ? l.tile_rough[tile_y * l.tiles_x + tile_x] : 0;
  __syncthreads();
  // The (n / 4)th smallest roughness, as the CPU's select_nth_unstable picks it.
  if (tile) {
    const int value = rough[t];
    int rank = 0;
    for (int u = 0; u < 64; u++) {
      const int ui = u % kRegion, uj = u / kRegion;
      if (ui >= nx || uj >= ny) continue;
      rank += rough[u] < value || (rough[u] == value && u < t);
    }
    if (rank == nx * ny / 4) quartile = value;
  }
  __syncthreads();
  const int floor = max(min(quartile * p.noise_factor, 255), p.min_contrast);
  if (t < 64) {
    uint8_t threshold = 0;
    if (tile) {
      int lo = 255, hi = 0;
      for (int y = max(tile_y - 1, 0); y < min(tile_y + 2, l.tiles_y); y++) {
        for (int x = max(tile_x - 1, 0); x < min(tile_x + 2, l.tiles_x); x++) {
          lo = min(lo, static_cast<int>(l.tile_min[y * l.tiles_x + x]));
          hi = max(hi, static_cast<int>(l.tile_max[y * l.tiles_x + x]));
        }
      }
      if (hi - lo >= floor) threshold = static_cast<uint8_t>((lo + hi + 1) / 2);
    }
    thresholds[t] = threshold;
  }
  __syncthreads();
  const int lane = t % 32, warp = t / 32;
  const int x = rx * 32 + lane;
  for (int r = warp; r < 32; r += blockDim.x / 32) {
    const int y = ry * 32 + r;
    if (y >= l.height) break;
    const bool dark = x < l.width &&
                      l.data[y * l.width + x] < thresholds[(r / kTile) * kRegion + lane / kTile];
    const uint32_t word = __ballot_sync(0xffffffffu, dark);
    if (lane == 0) l.mask[y * l.words + rx] = word;
  }
}

}  // namespace

extern "C" {

struct spot_dense_level {
  int32_t width, height;
};

}  // extern "C"

struct spot_dense {
  int32_t width, height;
  Params params;
  int regions;
  size_t mask_words;
  cudaStream_t stream;
  cudaStream_t copy_stream;  // the image copy, overlapping the kernels
  uint32_t *masks;       // device, all levels
  uint32_t *host_masks;  // pinned
  uint8_t *host_image;   // pinned, packed
  uint8_t *upload;       // device, packed
  void *device;          // device allocation for level data and tiles
};

static void release(spot_dense *self) {
  cudaFree(self->device);
  cudaFree(self->masks);
  cudaFree(self->upload);
  cudaFreeHost(self->host_masks);
  cudaFreeHost(self->host_image);
  if (self->stream != nullptr) cudaStreamDestroy(self->stream);
  if (self->copy_stream != nullptr) cudaStreamDestroy(self->copy_stream);
  delete self;
}

extern "C" spot_dense *spot_dense_new(int32_t width, int32_t height, int32_t step,
                                      int32_t min_contrast, int32_t noise_factor,
                                      const spot_dense_level *levels,
                                      int32_t count, char *error, int32_t len) {
  if (count < 1 || count > kMaxLevels) {
    std::snprintf(error, len, "unsupported level count %d", count);
    return nullptr;
  }
  auto *self = new (std::nothrow) spot_dense{};
  if (self == nullptr) return nullptr;
  self->width = width;
  self->height = height;
  Params &p = self->params;
  p.levels = count;
  p.step = step;
  p.start = step / 2;
  p.min_contrast = min_contrast;
  p.noise_factor = noise_factor;
  size_t bytes = 0;
  for (int k = 0; k < count; k++) {
    Level &l = p.level[k];
    l.width = levels[k].width;
    l.height = levels[k].height;
    l.words = (l.width + 31) / 32;
    l.tiles_x = (l.width + kTile - 1) / kTile;
    l.tiles_y = (l.height + kTile - 1) / kTile;
    l.regions_x = (l.tiles_x + kRegion - 1) / kRegion;
    l.regions_y = (l.tiles_y + kRegion - 1) / kRegion;
    p.region_start[k] = self->regions;
    self->regions += l.regions_x * l.regions_y;
    bytes += static_cast<size_t>(l.width) * l.height + 3 * static_cast<size_t>(l.tiles_x) * l.tiles_y;
    self->mask_words += static_cast<size_t>(l.words) * l.height;
  }
  p.region_start[count] = self->regions;
  cudaError_t status = cudaStreamCreateWithFlags(&self->stream, cudaStreamNonBlocking);
  if (status == cudaSuccess)
    status = cudaStreamCreateWithFlags(&self->copy_stream, cudaStreamNonBlocking);
  if (status == cudaSuccess) status = cudaMalloc(&self->device, bytes);
  if (status == cudaSuccess) status = cudaMalloc(&self->masks, self->mask_words * 4);
  if (status == cudaSuccess) status = cudaMallocHost(&self->host_masks, self->mask_words * 4);
  if (status == cudaSuccess)
    status = cudaMallocHost(&self->host_image, static_cast<size_t>(width) * height);
  if (status != cudaSuccess) {
    std::snprintf(error, len, "%s", cudaGetErrorString(status));
    release(self);
    return nullptr;
  }
  auto *cursor = static_cast<uint8_t *>(self->device);
  size_t words = 0;
  for (int k = 0; k < count; k++) {
    Level &l = p.level[k];
    const size_t tiles = static_cast<size_t>(l.tiles_x) * l.tiles_y;
    l.data = cursor;
    cursor += static_cast<size_t>(l.width) * l.height;
    l.tile_min = cursor;
    l.tile_max = cursor + tiles;
    l.tile_rough = cursor + 2 * tiles;
    cursor += 3 * tiles;
    l.mask = self->masks + words;
    words += static_cast<size_t>(l.words) * l.height;
  }
  return self;
}

// Copies a packed host image to device memory owned by the detector, returning its pointer.
extern "C" const uint8_t *spot_dense_upload(spot_dense *self, const uint8_t *image) {
  const size_t bytes = static_cast<size_t>(self->width) * self->height;
  if (self->upload == nullptr && cudaMalloc(&self->upload, bytes) != cudaSuccess) return nullptr;
  if (cudaMemcpy(self->upload, image, bytes, cudaMemcpyHostToDevice) != cudaSuccess) return nullptr;
  return self->upload;
}

// Runs the dense stage on a device image with rows `pitch` bytes apart. On success, points
// `masks` at every level's mask and `image` at a packed host copy of the image, both valid
// until the next run, and returns 0.
extern "C" int32_t spot_dense_run(spot_dense *self, const uint8_t *gray, int32_t pitch,
                                  const uint32_t **masks, const uint8_t **image, char *error,
                                  int32_t len) {
  const Params &p = self->params;
  const dim3 patches((p.level[0].width + kPatch - 1) / kPatch,
                     (p.level[0].height + kPatch - 1) / kPatch);
  cudaMemcpy2DAsync(self->host_image, self->width, gray, pitch, self->width, self->height,
                    cudaMemcpyDeviceToHost, self->copy_stream);
  sample_kernel<<<patches, dim3(32, 32), 0, self->stream>>>(gray, pitch, p);
  mask_kernel<<<self->regions, 256, 0, self->stream>>>(p);
  cudaMemcpyAsync(self->host_masks, self->masks, self->mask_words * 4, cudaMemcpyDeviceToHost,
                  self->stream);
  cudaError_t status = cudaStreamSynchronize(self->stream);
  if (status == cudaSuccess) status = cudaStreamSynchronize(self->copy_stream);
  if (status != cudaSuccess) {
    std::snprintf(error, len, "%s", cudaGetErrorString(status));
    return -1;
  }
  *masks = self->host_masks;
  *image = self->host_image;
  return 0;
}

extern "C" void spot_dense_free(spot_dense *self) { release(self); }
