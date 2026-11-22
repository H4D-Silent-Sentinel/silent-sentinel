// Rotor-comb detector. Port of cuas/detector.py; see that file for the
// algorithm description. Keep the two in lockstep.
#pragma once
#include <stdint.h>
#include "config.h"

struct FrameResult {
  uint32_t frame;
  bool hit;
  float f0;         // Hz
  float score;      // dB comb contrast
  int n_harm;
  float level_db;   // harmonic band level, dB SPL
  float floor_db;   // median per-bin background, dB SPL
  bool confirmed;
  bool steady;
  float f0_rate;    // Hz/s
  int confidence;   // 0..100
  bool clipping;
};

class CombDetector {
 public:
  bool begin();  // allocates buffers + tables; false on OOM / FFT init failure
  // ch[c] points to HOP new samples for mic c, full-scale units (±1.0).
  FrameResult process(const float *const ch[N_CH]);
  // C2 re-acquire hint: for the next `frames` frames, re-confirm on HINT_CONFIRM_HITS
  // hits within F0_TOL of f0_hz. frames == 0 cancels. Port of CombDetector.set_hint.
  void set_hint(float f0_hz, uint32_t frames) {
    hint_f0_ = frames ? f0_hz : 0.0f;
    hint_until_ = frames ? frame_ + frames : 0;
  }

 private:
  void spectrum_db();
  float refine_f0(float f0, const float *on_row) const;
  void update_confirm();
  void features(bool &steady, float &rate) const;

  // signal path
  float b_[3], a_[3];
  float z_[N_CH][2];
  float *buf_ = nullptr;   // [N_CH][N_FFT] sliding history
  float *win_ = nullptr;   // [N_FFT]
  float *fft_ = nullptr;   // [2*N_FFT] interleaved complex
  float win_norm_;
  float P_db_[K_MAX];
  float W_[K_MAX];
  float Wmax3_[K_MAX];
  float tonal_[K_MAX];

  // comb tables
  int16_t (*on_)[H_MAX] = nullptr;
  int16_t (*off_)[H_MAX] = nullptr;
  uint8_t n_h_[N_CAND];

  // history ring (hit, f0), oldest → newest via hist_at(i)
  bool hist_hit_[STEADY_WIN];
  float hist_f0_[STEADY_WIN];
  int hist_len_ = 0, hist_head_ = 0;
  void hist_push(bool hit, float f0);
  int hist_idx(int i) const { return (hist_head_ - hist_len_ + i + STEADY_WIN) % STEADY_WIN; }

  uint32_t frame_ = 0;
  bool confirmed_ = false;
  float hint_f0_ = 0.0f;
  uint32_t hint_until_ = 0;
};
