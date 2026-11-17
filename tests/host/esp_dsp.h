// Host stub of the two esp-dsp calls the detector uses (radix-2 complex FFT).
#pragma once
#include <math.h>
typedef int esp_err_t;
#define ESP_OK 0
static inline esp_err_t dsps_fft2r_init_fc32(float *, int) { return ESP_OK; }
static inline esp_err_t dsps_fft2r_fc32(float *, int) { return ESP_OK; }  // work is done in bit_rev below
// Do the whole FFT here (bit-reverse + iterative DIT) so the pair matches esp-dsp's result.
static inline esp_err_t dsps_bit_rev_fc32(float *d, int N) {
  for (int i = 1, j = 0; i < N; i++) {
    int bit = N >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { float t = d[2*i]; d[2*i] = d[2*j]; d[2*j] = t; t = d[2*i+1]; d[2*i+1] = d[2*j+1]; d[2*j+1] = t; }
  }
  for (int len = 2; len <= N; len <<= 1) {
    double ang = -2 * M_PI / len;
    for (int i = 0; i < N; i += len)
      for (int k = 0; k < len / 2; k++) {
        double wr = cos(ang * k), wi = sin(ang * k);
        float *a = d + 2 * (i + k), *b = d + 2 * (i + k + len / 2);
        double br = b[0] * wr - b[1] * wi, bi = b[0] * wi + b[1] * wr;
        b[0] = a[0] - br; b[1] = a[1] - bi; a[0] += br; a[1] += bi;
      }
  }
  return ESP_OK;
}
