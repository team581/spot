#include <thrust/iterator/constant_iterator.h>
#include <thrust/iterator/transform_iterator.h>

#include <cub/device/device_copy.cuh>
#include <cub/device/device_radix_sort.cuh>
#include <cub/device/device_reduce.cuh>
#include <cub/device/device_run_length_encode.cuh>
#include <cub/device/device_scan.cuh>
#include <cub/device/device_segmented_sort.cuh>
#include <cub/device/device_select.cuh>
#include <vector>

#include "apriltag_gpu.h"
#include "glog/logging.h"
#include "labeling_allegretti_2019_BKE.h"
#include "threshold.h"

namespace frc971::apriltag {
namespace {

void HostFitLine(LineFitMoments moments, double *lineparam01,
                 double *lineparam23, double *err, double *mse) {
  int64_t Cxx = moments.Mxx * moments.W - static_cast<int64_t>(moments.Mx) *
                                              static_cast<int64_t>(moments.Mx);
  int64_t Cxy = moments.Mxy * moments.W - static_cast<int64_t>(moments.Mx) *
                                              static_cast<int64_t>(moments.My);
  int64_t Cyy = moments.Myy * moments.W - static_cast<int64_t>(moments.My) *
                                              static_cast<int64_t>(moments.My);

  // Pose it as an eigenvalue problem.
  const float hypot_cached = std::hypotf((Cxx - Cyy), 2 * Cxy);
  const float eight_w_squared = static_cast<float>(
      static_cast<int64_t>(moments.W) * static_cast<int64_t>(moments.W) * 8.0);
  const float eig_small = (Cxx + Cyy - hypot_cached) / eight_w_squared;

  if (lineparam01) {
    lineparam01[0] =
        static_cast<float>(moments.Mx) / static_cast<float>(moments.W * 2);
    lineparam01[1] =
        static_cast<float>(moments.My) / static_cast<float>(moments.W * 2);
  }
  if (lineparam23) {
    // These don't match the originals at all, but the math should come out
    // right.  n{xy}{12} end up being multiplied by 8 W^2, and we compare the
    // square but use hypot on nx, ny directly.  (and let the W^2 term come out
    // as common to both the hypot and nxy terms.)
    const float nx1 = static_cast<float>(Cxx - Cyy) - hypot_cached;
    const float ny1 = Cxy * 2;
    const float M1 = nx1 * nx1 + ny1 * ny1;
    const float nx2 = Cxy * 2;
    const float ny2 = static_cast<float>(Cyy - Cxx) - hypot_cached;
    const float M2 = nx2 * nx2 + ny2 * ny2;

    float nx, ny;
    if (M1 > M2) {
      nx = nx1;
      ny = ny1;
    } else {
      nx = nx2;
      ny = ny2;
    }

    float length = std::hypotf(nx, ny);
    lineparam23[0] = nx / length;
    lineparam23[1] = ny / length;
  }

  // sum of squared errors
  *err = moments.N * eig_small;

  // mean squared error
  *mse = eig_small;
}

}  // namespace

void GpuDetector::UpdateFitQuads() {
  quad_corners_host_.resize(0);
  VLOG(1) << "Considering " << fit_quads_host_.size();
  for (const FitQuad &quad : fit_quads_host_) {
    if (!quad.valid) {
      continue;
    }
    QuadCorners corners;
    corners.blob_index = quad.blob_index;
    CHECK(normal_border_ != reversed_border_);
    corners.reversed_border = reversed_border_;

    double lines[4][4];
    for (int i = 0; i < 4; i++) {
      double err;
      double mse;
      HostFitLine(quad.moments[i], lines[i], lines[i] + 2, &err, &mse);
    }

    bool bad_determinant = false;
    for (int i = 0; i < 4; i++) {
      // solve for the intersection of lines (i) and (i+1)&3.
      // p0 + lambda0*u0 = p1 + lambda1*u1, where u0 and u1
      // are the line directions.
      //
      // lambda0*u0 - lambda1*u1 = (p1 - p0)
      //
      // rearrange (solve for lambdas)
      //
      // [u0_x   -u1_x ] [lambda0] = [ p1_x - p0_x ]
      // [u0_y   -u1_y ] [lambda1]   [ p1_y - p0_y ]
      //
      // remember that lines[i][0,1] = p, lines[i][2,3] = NORMAL vector.
      // We want the unit vector, so we need the perpendiculars. Thus, below
      // we have swapped the x and y components and flipped the y components.

      double A00 = lines[i][3], A01 = -lines[(i + 1) & 3][3];
      double A10 = -lines[i][2], A11 = lines[(i + 1) & 3][2];
      double B0 = -lines[i][0] + lines[(i + 1) & 3][0];
      double B1 = -lines[i][1] + lines[(i + 1) & 3][1];

      double det = A00 * A11 - A10 * A01;

      // inverse.
      double W00 = A11 / det, W01 = -A01 / det;
      if (fabs(det) < 0.001) {
        bad_determinant = true;
        break;
      }

      // solve
      double L0 = W00 * B0 + W01 * B1;

      // compute intersection
      corners.corners[i][0] = lines[i][0] + L0 * A00;
      corners.corners[i][1] = lines[i][1] + L0 * A10;
    }
    if (bad_determinant) {
      continue;
    }

    {
      float area = 0;

      // get area of triangle formed by points 0, 1, 2, 0
      float length[3], p;
      for (int i = 0; i < 3; i++) {
        int idxa = i;            // 0, 1, 2,
        int idxb = (i + 1) % 3;  // 1, 2, 0
        length[i] =
            hypotf((corners.corners[idxb][0] - corners.corners[idxa][0]),
                   (corners.corners[idxb][1] - corners.corners[idxa][1]));
      }
      p = (length[0] + length[1] + length[2]) / 2;

      area += sqrtf(p * (p - length[0]) * (p - length[1]) * (p - length[2]));

      // get area of triangle formed by points 2, 3, 0, 2
      for (int i = 0; i < 3; i++) {
        int idxs[] = {2, 3, 0, 2};
        int idxa = idxs[i];
        int idxb = idxs[i + 1];
        length[i] =
            hypotf((corners.corners[idxb][0] - corners.corners[idxa][0]),
                   (corners.corners[idxb][1] - corners.corners[idxa][1]));
      }
      p = (length[0] + length[1] + length[2]) / 2;

      area += sqrtf(p * (p - length[0]) * (p - length[1]) * (p - length[2]));

      if (area < 0.95 * min_tag_width_ * min_tag_width_) {
        continue;
      }
    }

    // reject quads whose cumulative angle change isn't equal to 2PI
    {
      bool reject_corner = false;
      for (int i = 0; i < 4; i++) {
        int i0 = i, i1 = (i + 1) & 3, i2 = (i + 2) & 3;

        float dx1 = corners.corners[i1][0] - corners.corners[i0][0];
        float dy1 = corners.corners[i1][1] - corners.corners[i0][1];
        float dx2 = corners.corners[i2][0] - corners.corners[i1][0];
        float dy2 = corners.corners[i2][1] - corners.corners[i1][1];
        float cos_dtheta =
            (dx1 * dx2 + dy1 * dy2) /
            sqrtf((dx1 * dx1 + dy1 * dy1) * (dx2 * dx2 + dy2 * dy2));


        if (std::abs(cos_dtheta) > kCosCriticalRad ||
            dx1 * dy2 < dy1 * dx2) {
          reject_corner = true;
          break;
        }
      }
      if (reject_corner) {
        continue;
      }
    }
    quad_corners_host_.push_back(corners);
  }
}

void GpuDetector::AdjustPixelCenters() {
  for (QuadCorners &quad : quad_corners_host_) {
    for (int j = 0; j < 4; j++) {
      quad.corners[j][0] = (quad.corners[j][0] - 0.5f) * kQuadDecimate + 0.5f;
      quad.corners[j][1] = (quad.corners[j][1] - 0.5f) * kQuadDecimate + 0.5f;
    }
  }
}

}  // namespace frc971::apriltag
