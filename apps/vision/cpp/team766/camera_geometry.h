// Host-side edge refinement for the CUDA detector's quads, from Team 766's
// https://github.com/Team766/apriltags_cuda.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
namespace frc971::apriltag {
struct CameraMatrix { double fx; double cx; double fy; double cy; };
struct DistCoeffs { double k1; double k2; double p1; double p2; double k3; };
// Dewarps points from the image based on various constants
// Algorithm mainly taken from
// https://docs.opencv.org/4.0.0/d9/d0c/group__calib3d.html#ga7dfb72c9cf9780a347fbe3d1c47e5d5a
inline void ReDistort(double *x, double *y, CameraMatrix *camera_matrix,
               DistCoeffs *distortion_coefficients) {
  double k1 = distortion_coefficients->k1;
  double k2 = distortion_coefficients->k2;
  double p1 = distortion_coefficients->p1;
  double p2 = distortion_coefficients->p2;
  double k3 = distortion_coefficients->k3;

  double fx = camera_matrix->fx;
  double cx = camera_matrix->cx;
  double fy = camera_matrix->fy;
  double cy = camera_matrix->cy;

  double xP = (*x - cx) / fx;
  double yP = (*y - cy) / fy;

  double rSq = xP * xP + yP * yP;

  double linCoef = 1 + k1 * rSq + k2 * rSq * rSq + k3 * rSq * rSq * rSq;
  double xPP = xP * linCoef + 2 * p1 * xP * yP + p2 * (rSq + 2 * xP * xP);
  double yPP = yP * linCoef + p1 * (rSq + 2 * yP * yP) + 2 * p2 * xP * yP;

  *x = xPP * fx + cx;
  *y = yPP * fy + cy;
}

// Invert the same five-coefficient Brown-Conrady model used by ReDistort.
// Preserve the caller's point when inversion fails.
inline bool UnDistort(double *u, double *v, const CameraMatrix *camera,
                     const DistCoeffs *distortion) {
  if (!std::isfinite(*u) || !std::isfinite(*v) ||
      !std::isfinite(camera->fx) || !std::isfinite(camera->fy) ||
      camera->fx <= 0 || camera->fy <= 0) return false;
  const double x0 = (*u - camera->cx) / camera->fx;
  const double y0 = (*v - camera->cy) / camera->fy;
  double x = x0, y = y0;
  for (int iteration = 0; iteration < 100; ++iteration) {
    const double r2 = x * x + y * y;
    const double radial = 1 + distortion->k1 * r2 + distortion->k2 * r2 * r2 +
                          distortion->k3 * r2 * r2 * r2;
    if (!std::isfinite(radial) || radial <= 1e-12) return false;
    const double dx = 2 * distortion->p1 * x * y + distortion->p2 * (r2 + 2 * x * x);
    const double dy = distortion->p1 * (r2 + 2 * y * y) + 2 * distortion->p2 * x * y;
    const double next_x = (x0 - dx) / radial;
    const double next_y = (y0 - dy) / radial;
    if (!std::isfinite(next_x) || !std::isfinite(next_y)) return false;
    double px = next_x * camera->fx + camera->cx;
    double py = next_y * camera->fy + camera->cy;
    // Convergence is measured in raw pixels, not normalized camera coordinates.
    CameraMatrix forward_camera = *camera;
    DistCoeffs forward_distortion = *distortion;
    ReDistort(&px, &py, &forward_camera, &forward_distortion);
    if (std::hypot(px - *u, py - *v) < 1e-6) {
      *u = next_x * camera->fx + camera->cx;
      *v = next_y * camera->fy + camera->cy;
      return true;
    }
    x = next_x;
    y = next_y;
  }
  return false;
}

// Mostly stolen from aprilrobotics, but modified to implement the dewarp.
// `p` holds a quad's corners in image pixels, wound like umich AprilTag's quads.
// `range` is how far from each edge to search, in pixels.
inline void RefineEdges(const uint8_t *im, int width, int height, double range,
                 float p[4][2], bool reversed_border, CameraMatrix *camera_matrix,
                 DistCoeffs *distortion_coefficients) {
  double lines[4][4];  // for each line, [Ex Ey nx ny]

  for (int edge = 0; edge < 4; edge++) {
    int a = edge, b = (edge + 1) & 3;  // indices of the end points.

    // compute the normal to the current line estimate
    float nx = p[b][1] - p[a][1];
    float ny = -p[b][0] + p[a][0];
    float mag = sqrtf(nx * nx + ny * ny);
    if (!std::isfinite(mag) || mag < 1e-6) return;
    nx /= mag;
    ny /= mag;

    if (reversed_border) {
      nx = -nx;
      ny = -ny;
    }

    // we will now fit a NEW line by sampling points near
    // our original line that have large gradients. On really big tags,
    // we're willing to sample more to get an even better estimate.
    int nsamples = std::max<int>(16, mag / 8);  // XXX tunable

    // stats for fitting a line...
    double Mx = 0, My = 0, Mxx = 0, Mxy = 0, Myy = 0, N = 0;

    for (int s = 0; s < nsamples; s++) {
      // compute a point along the line... Note, we're avoiding
      // sampling *right* at the corners, since those points are
      // the least reliable.
      double alpha = (1.0 + s) / (nsamples + 1);
      double x0 = alpha * p[a][0] + (1 - alpha) * p[b][0];
      double y0 = alpha * p[a][1] + (1 - alpha) * p[b][1];

      // search along the normal to this line, looking at the
      // gradients along the way. We're looking for a strong
      // response.
      double Mn = 0;
      double Mcount = 0;

      // XXX tunable: how far to search?  We want to search far
      // enough that we find the best edge, but not so far that
      // we hit other edges that aren't part of the tag. We
      // shouldn't ever have to search more than quad_decimate,
      // since otherwise we would (ideally) have started our
      // search on another pixel in the first place. Likewise,
      // for very small tags, we don't want the range to be too
      // big.
      
      // XXX tunable step size.
      for (double n = -range; n <= range; n += 0.25) {
        // Because of the guaranteed winding order of the
        // points in the quad, we will start inside the white
        // portion of the quad and work our way outward.
        //
        // sample to points (x1,y1) and (x2,y2) XXX tunable:
        // how far +/- to look? Small values compute the
        // gradient more precisely, but are more sensitive to
        // noise.
        double grange = 1;
        int x1 = x0 + (n + grange) * nx;
        int y1 = y0 + (n + grange) * ny;
        if (x1 < 0 || x1 >= width || y1 < 0 || y1 >= height)
          continue;

        int x2 = x0 + (n - grange) * nx;
        int y2 = y0 + (n - grange) * ny;
        if (x2 < 0 || x2 >= width || y2 < 0 || y2 >= height)
          continue;

        int g1 = im[y1 * width + x1];
        int g2 = im[y2 * width + x2];

        if (g1 < g2)  // reject points whose gradient is "backwards". They can
                      // only hurt us.
          continue;

        double weight =
            (g2 - g1) *
            (g2 - g1);  // XXX tunable. What shape for weight=f(g2-g1)?

        // compute weighted average of the gradient at this point.
        Mn += weight * n;
        Mcount += weight;
      }

      // what was the average point along the line?
      if (Mcount == 0) continue;

      double n0 = Mn / Mcount;

      // where is the point along the line?
      double bestx = x0 + n0 * nx;
      double besty = y0 + n0 * ny;

      // Fit straight lines only after mapping sampled gradients to the ideal plane.
      if (!UnDistort(&bestx, &besty, camera_matrix, distortion_coefficients)) continue;

      // update our line fit statistics
      Mx += bestx;
      My += besty;
      Mxx += bestx * bestx;
      Mxy += bestx * besty;
      Myy += besty * besty;
      N++;
    }

    // Keep the original quad if an edge has insufficient usable samples.
    if (N < 2) return;

    // fit a line
    double Ex = Mx / N, Ey = My / N;
    double Cxx = Mxx / N - Ex * Ex;
    double Cxy = Mxy / N - Ex * Ey;
    double Cyy = Myy / N - Ey * Ey;

    // TODO: Can replace this with same code as in fit_line.
    double normal_theta = .5 * atan2f(-2 * Cxy, (Cyy - Cxx));
    nx = cosf(normal_theta);
    ny = sinf(normal_theta);
    lines[edge][0] = Ex;
    lines[edge][1] = Ey;
    lines[edge][2] = nx;
    lines[edge][3] = ny;
  }

  // now refit the corners of the quad
  for (int i = 0; i < 4; i++) {
    // solve for the intersection of lines (i) and (i+1)&3.
    double A00 = lines[i][3], A01 = -lines[(i + 1) & 3][3];
    double A10 = -lines[i][2], A11 = lines[(i + 1) & 3][2];
    double B0 = -lines[i][0] + lines[(i + 1) & 3][0];
    double B1 = -lines[i][1] + lines[(i + 1) & 3][1];

    double det = A00 * A11 - A10 * A01;

    // inverse.
    if (fabs(det) > 0.001) {
      // solve
      double W00 = A11 / det, W01 = -A01 / det;

      double L0 = W00 * B0 + W01 * B1;

      // Compute intersection. Note that line i represents the line from corner
      // i to (i+1)&3, so the intersection of line i with line (i+1)&3
      // represents corner (i+1)&3.
      double px = lines[i][0] + L0 * A00;
      double py = lines[i][1] + L0 * A10;

      ReDistort(&px, &py, camera_matrix, distortion_coefficients);
      if (!std::isfinite(px) || !std::isfinite(py)) continue;
      p[(i + 1) & 3][0] = px;
      p[(i + 1) & 3][1] = py;
    } else {
      // this is a bad sign. We'll just keep the corner we had.
      //            debug_print("bad det: %15f %15f %15f %15f %15f\n", A00, A11,
      //            A10, A01, det);
    }
  }
}


}  // namespace frc971::apriltag
