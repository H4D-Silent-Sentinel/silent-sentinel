// Feeds raw float32 [4][n] from stdin-file through the firmware detector, prints one CSV line per frame.
#include <cstdlib>
#include <stdio.h>
#include <vector>
#include "../../firmware/node/detector.h"
int main(int argc, char **argv) {
  FILE *f = fopen(argv[1], "rb");
  long n = atol(argv[2]);
  std::vector<float> x(4 * n);
  fread(x.data(), sizeof(float), x.size(), f);
  static CombDetector det;
  if (!det.begin()) return 1;
  if (argc >= 5) det.set_hint(atof(argv[3]), (uint32_t)atol(argv[4]));  // optional C2 hint
  for (long s = 0; s + HOP <= n; s += HOP) {
    const float *ch[4] = {&x[0 * n + s], &x[1 * n + s], &x[2 * n + s], &x[3 * n + s]};
    FrameResult r = det.process(ch);
    printf("%u,%d,%.3f,%.3f,%d,%.2f,%.2f,%d,%d,%.3f,%d\n", r.frame, r.hit, r.f0, r.score, r.n_harm,
           r.level_db, r.floor_db, r.confirmed, r.steady, r.f0_rate, r.confidence);
  }
}
