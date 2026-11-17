#include "detector.h"

#include <math.h>
#include <string.h>
#include <algorithm>

#include "esp_dsp.h"
#include "esp_heap_caps.h"

static void *alloc(size_t n) {
  void *p = heap_caps_malloc(n, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  if (!p) p = heap_caps_malloc(n, MALLOC_CAP_SPIRAM);
  if (p) memset(p, 0, n);
  return p;
}

bool CombDetector::begin() {
  // RBJ 2nd-order Butterworth high-pass
  float w0 = 2.0f * (float)M_PI * HPF_HZ / FS;
  float alpha = sinf(w0) / (2.0f * 0.70710678f);
  float c = cosf(w0);
  float a0 = 1 + alpha;
  b_[0] = (1 + c) / 2 / a0;  b_[1] = -(1 + c) / a0;  b_[2] = (1 + c) / 2 / a0;
  a_[0] = 1;                 a_[1] = -2 * c / a0;    a_[2] = (1 - alpha) / a0;
  memset(z_, 0, sizeof(z_));

  buf_ = (float *)alloc(sizeof(float) * N_CH * N_FFT);
  win_ = (float *)alloc(sizeof(float) * N_FFT);
  fft_ = (float *)alloc(sizeof(float) * 2 * N_FFT);
  on_ = (int16_t(*)[H_MAX])alloc(sizeof(int16_t) * N_CAND * H_MAX);
  off_ = (int16_t(*)[H_MAX])alloc(sizeof(int16_t) * N_CAND * H_MAX);
  if (!buf_ || !win_ || !fft_ || !on_ || !off_) return false;

  double wsum = 0;
  for (int n = 0; n < N_FFT; n++) {
    win_[n] = 0.5f - 0.5f * cosf(2.0f * (float)M_PI * n / N_FFT);
    wsum += win_[n];
  }
  win_norm_ = (float)(4.0 / (wsum * wsum));

  for (int i = 0; i < N_CAND; i++) {
    float f0 = F0_MIN + i * F0_STEP;
    n_h_[i] = (uint8_t)std::min(H_MAX, (int)floorf(FMAX_HARM / f0));
    for (int h = 1; h <= H_MAX; h++) {
      int on = (int)lroundf(h * f0 / DF), off = (int)lroundf((h + 0.5f) * f0 / DF);
      on_[i][h - 1] = (int16_t)std::max(1, std::min(K_MAX - 2, on));
      off_[i][h - 1] = (int16_t)std::max(1, std::min(K_MAX - 2, off));
    }
  }
  memset(tonal_, 0, sizeof(tonal_));
  return dsps_fft2r_init_fc32(NULL, N_FFT) == ESP_OK;
}

void CombDetector::hist_push(bool hit, float f0) {
  hist_hit_[hist_head_] = hit;
  hist_f0_[hist_head_] = f0;
  hist_head_ = (hist_head_ + 1) % STEADY_WIN;
  if (hist_len_ < STEADY_WIN) hist_len_++;
}

// Two real mics per complex FFT: z = a + jb. Then
// |A_k|² + |B_k|² = (|Z_k|² + |Z_{N-k}|²) / 2, which is all we need.
void CombDetector::spectrum_db() {
  static float P[K_MAX];
  memset(P, 0, sizeof(P));
  for (int pair = 0; pair < N_CH / 2; pair++) {
    const float *a = buf_ + (2 * pair) * N_FFT;
    const float *b = buf_ + (2 * pair + 1) * N_FFT;
    for (int n = 0; n < N_FFT; n++) {
      fft_[2 * n] = a[n] * win_[n];
      fft_[2 * n + 1] = b[n] * win_[n];
    }
    dsps_fft2r_fc32(fft_, N_FFT);
    dsps_bit_rev_fc32(fft_, N_FFT);
    for (int k = 0; k < K_MAX; k++) {
      int m = (N_FFT - k) % N_FFT;
      float re1 = fft_[2 * k], im1 = fft_[2 * k + 1];
      float re2 = fft_[2 * m], im2 = fft_[2 * m + 1];
      P[k] += 0.5f * (re1 * re1 + im1 * im1 + re2 * re2 + im2 * im2);
    }
  }
  for (int k = 0; k < K_MAX; k++) P_db_[k] = 10.0f * log10f(P[k] / N_CH * win_norm_ + 1e-20f);
}

FrameResult CombDetector::process(const float *const ch[N_CH]) {
  FrameResult r{};
  r.frame = frame_;

  // 1. high-pass + slide history
  float peak = 0;
  for (int c = 0; c < N_CH; c++) {
    float *h = buf_ + c * N_FFT;
    memmove(h, h + HOP, sizeof(float) * (N_FFT - HOP));
    float *dst = h + (N_FFT - HOP);
    float z1 = z_[c][0], z2 = z_[c][1];
    for (int n = 0; n < HOP; n++) {
      float x = ch[c][n];
      peak = std::max(peak, fabsf(x));
      float y = b_[0] * x + z1;  // direct form II transposed
      z1 = b_[1] * x - a_[1] * y + z2;
      z2 = b_[2] * x - a_[2] * y;
      dst[n] = y;
    }
    z_[c][0] = z1; z_[c][1] = z2;
  }
  r.clipping = peak > 0.99f;

  // 2. spectrum
  spectrum_db();

  // 3. whiten against running median across frequency ('nearest' edges)
  float win[MEDIAN_BINS];
  const int half = MEDIAN_BINS / 2;
  for (int k = 0; k < K_MAX; k++) {
    for (int j = -half; j <= half; j++) win[j + half] = P_db_[std::max(0, std::min(K_MAX - 1, k + j))];
    std::nth_element(win, win + half, win + MEDIAN_BINS);
    W_[k] = P_db_[k] - win[half];
  }

  // 4. long-term tonal mask, then clip
  for (int k = 0; k < K_MAX; k++) {
    tonal_[k] += TONAL_ALPHA * ((W_[k] > HARM_DB ? 1.0f : 0.0f) - tonal_[k]);
    float w = tonal_[k] > TONAL_MASK ? 0.0f : W_[k];
    W_[k] = std::max(W_CLIP_LO, std::min(W_CLIP_HI, w));
  }
  Wmax3_[0] = W_[0];
  Wmax3_[K_MAX - 1] = W_[K_MAX - 1];
  for (int k = 1; k < K_MAX - 1; k++) Wmax3_[k] = std::max(W_[k - 1], std::max(W_[k], W_[k + 1]));

  // 5. comb search
  int best = 0;
  float best_score = -1e9f;
  for (int i = 0; i < N_CAND; i++) {
    float s = 0;
    for (int h = 0; h < n_h_[i]; h++) s += Wmax3_[on_[i][h]] - Wmax3_[off_[i][h]];
    s /= n_h_[i];
    if (s > best_score) { best_score = s; best = i; }  // first max wins, like np.argmax
  }
  float on_row[H_MAX] = {0};
  int n_harm = 0;
  for (int h = 0; h < n_h_[best]; h++) {
    on_row[h] = Wmax3_[on_[best][h]];
    if (on_row[h] > HARM_DB) n_harm++;
  }
  float f0_grid = F0_MIN + best * F0_STEP;
  r.f0 = refine_f0(f0_grid, on_row);
  r.score = best_score;
  r.n_harm = n_harm;

  double lin = 0;
  for (int h = 0; h < n_h_[best]; h++) lin += pow(10.0, P_db_[on_[best][h]] / 10.0);
  r.level_db = 10.0f * (float)log10(lin) + SPL_OFFSET;

  {  // floor: median of bins [100 Hz, 3000 Hz)
    const int lo = (int)(100.0f / DF), hi = (int)(FMAX_HARM / DF);
    static float tmp[K_MAX];
    int n = hi - lo;
    memcpy(tmp, P_db_ + lo, sizeof(float) * n);
    std::sort(tmp, tmp + n);
    float med = (n % 2) ? tmp[n / 2] : 0.5f * (tmp[n / 2 - 1] + tmp[n / 2]);
    r.floor_db = med + SPL_OFFSET;
  }

  // 6. confirm
  bool warm = frame_ >= WARMUP_FRAMES;
  r.hit = warm && best_score >= SCORE_DB && n_harm >= MIN_HARM;
  hist_push(r.hit, r.f0);
  update_confirm();
  features(r.steady, r.f0_rate);
  r.confirmed = confirmed_;

  // 7. confidence
  if (confirmed_) {
    float c = 60.0f * std::max(0.0f, std::min(1.0f, (best_score - SCORE_DB) / 14.0f));
    c += 30.0f * std::max(0.0f, std::min(1.0f, (n_harm - MIN_HARM) / 6.0f));
    c += r.steady ? 0.0f : 10.0f;
    r.confidence = (int)lroundf(c);
  }
  frame_++;
  return r;
}

float CombDetector::refine_f0(float f0, const float *on_row) const {
  double num = 0, den = 0;
  for (int h = 1; h <= H_MAX; h++) {
    if (h * f0 > FMAX_HARM || on_row[h - 1] <= HARM_DB) continue;
    int c = (int)lroundf(h * f0 / DF);
    int k = c - 1;
    if (P_db_[c] > P_db_[k]) k = c;
    if (P_db_[c + 1] > P_db_[k]) k = c + 1;
    if (k < 1 || k > K_MAX - 2) continue;
    float a = P_db_[k - 1], b = P_db_[k], g = P_db_[k + 1];
    float d = a - 2 * b + g;
    float delta = d < 0 ? 0.5f * (a - g) / d : 0.0f;
    delta = std::max(-0.5f, std::min(0.5f, delta));
    num += h * (k + delta) * DF;
    den += h * h;
  }
  return den > 0 ? (float)(num / den) : f0;
}

void CombDetector::update_confirm() {
  float f0s[CONFIRM_WIN];
  int n = 0;
  int start = std::max(0, hist_len_ - CONFIRM_WIN);
  for (int i = start; i < hist_len_; i++) {
    int j = hist_idx(i);
    if (hist_hit_[j]) f0s[n++] = hist_f0_[j];
  }
  if (!confirmed_) {
    if (n >= CONFIRM_HITS) {
      float s[CONFIRM_WIN];
      memcpy(s, f0s, sizeof(float) * n);
      std::sort(s, s + n);
      float m = (n % 2) ? s[n / 2] : 0.5f * (s[n / 2 - 1] + s[n / 2]);
      int agree = 0;
      for (int i = 0; i < n; i++) agree += fabsf(f0s[i] - m) <= F0_TOL * m;
      confirmed_ = agree >= CONFIRM_HITS;
    }
  } else if (n < RELEASE_HITS) {
    confirmed_ = false;
  }
}

void CombDetector::features(bool &steady, float &rate) const {
  // steady: relative std of f0 over hits in the last STEADY_WIN frames
  double s = 0, s2 = 0;
  int n = 0;
  for (int i = 0; i < hist_len_; i++) {
    int j = hist_idx(i);
    if (!hist_hit_[j]) continue;
    s += hist_f0_[j]; s2 += (double)hist_f0_[j] * hist_f0_[j]; n++;
  }
  steady = false;
  if (n >= STEADY_MIN) {
    double mean = s / n, var = std::max(0.0, s2 / n - mean * mean);
    steady = sqrt(var) / mean < STEADY_REL_STD;
  }
  // rate: least-squares slope of f0 vs time over hits in the last SLOPE_WIN frames
  int start = std::max(0, hist_len_ - SLOPE_WIN);
  double t[SLOPE_WIN], f[SLOPE_WIN];
  int m = 0;
  for (int i = start; i < hist_len_; i++) {
    int j = hist_idx(i);
    if (hist_hit_[j]) { t[m] = (i - start) / FRAME_RATE; f[m] = hist_f0_[j]; m++; }
  }
  rate = 0;
  if (m >= 4) {
    double tm = 0, fm = 0;
    for (int i = 0; i < m; i++) { tm += t[i]; fm += f[i]; }
    tm /= m; fm /= m;
    double num = 0, den = 0;
    for (int i = 0; i < m; i++) { num += (t[i] - tm) * (f[i] - fm); den += (t[i] - tm) * (t[i] - tm); }
    rate = den > 0 ? (float)(num / den) : 0;
  }
}
