//! Full 6-DOF robot pose from AprilTag corners seen by one camera.
//!
//! Seeds come from a yaw sweep with the robot flat on the floor: for a fixed yaw the camera
//! projection is linear in x and y, so linear least squares finds each local minimum. Every
//! seed is then refined over x, y, z, roll, pitch, and yaw with Levenberg-Marquardt on the
//! pixel reprojection error plus a soft prior toward a flat robot on the floor.
//!
//! Far tags barely constrain height and tilt, so a physically wrong pose can fit the pixels
//! slightly better than the real one (ex. 0.8 m underground and pitched 10°). The prior breaks
//! those near-ties, while tags that clearly show a real tilt or height still win.

use std::f64::consts::{PI, TAU};

use nalgebra::{
    Isometry3, Matrix2, Matrix3, Matrix6, Point3, UnitQuaternion, Vector2, Vector3, Vector6,
};

use crate::config::Calibration;

/// One tag's corners: detected pixels and field positions, in detector order.
pub struct TagObservation {
    pub id: u32,
    pub pixels: [[f64; 2]; 4],
    pub field: [Point3<f64>; 4],
}

#[derive(Debug, Clone)]
pub struct Candidate {
    /// Robot pose on the field.
    pub pose: Isometry3<f64>,
    /// RMS corner reprojection error in pixels.
    pub error: f64,
}

#[derive(Debug, Clone)]
pub struct Estimate {
    pub primary: Candidate,
    pub alternate: Option<Candidate>,
    /// Bit `n` is set when tag `n` (0-63) contributed.
    pub tag_ids: i64,
    /// Mean camera-to-tag-center distance in meters, using the primary candidate.
    pub average_tag_distance: f64,
    /// Sum of tag areas as a fraction of the image area.
    pub tag_area: f64,
}

/// Field positions of a tag's corners in detector order: bottom-left, bottom-right,
/// top-right, top-left as seen facing the tag. WPILib tag frames point +X out of the face.
/// FRC AprilTag (36h11) edge length in meters, measured across the outer black border.
pub const TAG_SIZE: f64 = 0.1651;

pub fn tag_corners(tag: &Isometry3<f64>, size: f64) -> [Point3<f64>; 4] {
    let h = size / 2.0;
    [(-h, -h), (h, -h), (h, h), (-h, h)].map(|(y, z)| tag * Point3::new(0.0, y, z))
}

/// Undistorts a pixel to normalized pinhole coordinates (OpenCV's iterative method).
pub fn undistort(pixel: [f64; 2], k: &Calibration) -> Vector2<f64> {
    let [k1, k2, p1, p2, k3] = k.distortion;
    let x0 = (pixel[0] - k.cx) / k.fx;
    let y0 = (pixel[1] - k.cy) / k.fy;
    let (mut x, mut y) = (x0, y0);
    for _ in 0..20 {
        let r2 = x * x + y * y;
        let radial = 1.0 + r2 * (k1 + r2 * (k2 + r2 * k3));
        let dx = 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x);
        let dy = p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y;
        x = (x0 - dx) / radial;
        y = (y0 - dy) / radial;
    }
    Vector2::new(x, y)
}

/// WPILib camera axes (+X forward, +Y left, +Z up) to optical axes (+X right, +Y down, +Z forward).
const OPTICAL: Matrix3<f64> = Matrix3::new(0.0, -1.0, 0.0, 0.0, 0.0, -1.0, 1.0, 0.0, 0.0);

struct Problem {
    /// Field corner positions.
    field: Vec<Vector3<f64>>,
    /// Undistorted normalized image coordinates.
    image: Vec<Vector2<f64>>,
    /// Optical-from-robot rotation and camera position in the robot frame.
    mount_rotation: Matrix3<f64>,
    mount_offset: Vector3<f64>,
    focal: Vector2<f64>,
}

/// One standard deviation of the floor prior. Pixel residuals are roughly 1 px, so a robot
/// this far from flat costs as much as 1 px of extra reprojection error.
const FLOOR_HEIGHT_SIGMA: f64 = 0.1;
const FLOOR_TILT_SIGMA: f64 = 5.0 * PI / 180.0;

/// Robot pose parameters: x, y, z in meters, then roll, pitch, yaw in radians.
type Params = [f64; 6];

fn rotation(params: &Params) -> UnitQuaternion<f64> {
    UnitQuaternion::from_euler_angles(params[3], params[4], params[5])
}

impl Problem {
    /// Optical-frame point `o = A (P - T) - c` for the robot rotation and position `T`.
    fn transform(&self, rotation: &UnitQuaternion<f64>) -> (Matrix3<f64>, Vector3<f64>) {
        let a = self.mount_rotation * rotation.to_rotation_matrix().matrix().transpose();
        (a, self.mount_rotation * self.mount_offset)
    }

    /// Best x and y for a flat robot at a fixed yaw, from the linear projection constraints.
    fn translation(&self, theta: f64) -> Option<Vector2<f64>> {
        let (a, c) = self.transform(&UnitQuaternion::from_euler_angles(0.0, 0.0, theta));
        let mut normal = Matrix2::zeros();
        let mut rhs = Vector2::zeros();
        for (p, uv) in self.field.iter().zip(&self.image) {
            let d = a * p - c;
            for (row, value) in [(0, uv.x), (1, uv.y)] {
                let j =
                    Vector2::new(a[(row, 0)] - value * a[(2, 0)], a[(row, 1)] - value * a[(2, 1)]);
                normal += j * j.transpose();
                rhs += j * (d[row] - value * d.z);
            }
        }
        normal.try_inverse().map(|inverse| inverse * rhs)
    }

    /// Pixel residuals followed by the floor prior, or `None` if any corner is behind the camera.
    fn residuals(&self, params: &Params) -> Option<Vec<f64>> {
        let (a, c) = self.transform(&rotation(params));
        let t = Vector3::new(params[0], params[1], params[2]);
        let mut residuals = Vec::with_capacity(self.field.len() * 2 + 3);
        for (p, uv) in self.field.iter().zip(&self.image) {
            let o = a * (p - t) - c;
            if o.z <= 1e-6 {
                return None;
            }
            residuals.push((o.x / o.z - uv.x) * self.focal.x);
            residuals.push((o.y / o.z - uv.y) * self.focal.y);
        }
        residuals.push(params[2] / FLOOR_HEIGHT_SIGMA);
        residuals.push(params[3] / FLOOR_TILT_SIGMA);
        residuals.push(params[4] / FLOOR_TILT_SIGMA);
        Some(residuals)
    }

    fn cost(&self, params: &Params) -> f64 {
        self.residuals(params).map_or(f64::INFINITY, |r| r.iter().map(|v| v * v).sum())
    }

    /// RMS corner reprojection error in pixels, without the prior.
    fn pixel_error(&self, params: &Params) -> f64 {
        self.residuals(params).map_or(f64::INFINITY, |r| {
            let pixels = &r[..self.field.len() * 2];
            (pixels.iter().map(|v| v * v).sum::<f64>() / self.field.len() as f64).sqrt()
        })
    }

    fn refine(&self, mut params: Params) -> Params {
        let mut cost = self.cost(&params);
        let mut lambda = 1e-3;
        for _ in 0..50 {
            let Some(r) = self.residuals(&params) else { break };
            let steps = [1e-6, 1e-6, 1e-6, 1e-7, 1e-7, 1e-7];
            let mut jacobian = vec![[0.0; 6]; r.len()];
            for k in 0..6 {
                let (mut plus, mut minus) = (params, params);
                plus[k] += steps[k];
                minus[k] -= steps[k];
                let (Some(rp), Some(rm)) = (self.residuals(&plus), self.residuals(&minus)) else {
                    return params;
                };
                for i in 0..r.len() {
                    jacobian[i][k] = (rp[i] - rm[i]) / (2.0 * steps[k]);
                }
            }
            let mut jtj = Matrix6::zeros();
            let mut jtr = Vector6::zeros();
            for (row, ri) in jacobian.iter().zip(&r) {
                let j = Vector6::from(*row);
                jtj += j * j.transpose();
                jtr += j * *ri;
            }
            let mut improved = false;
            while lambda < 1e8 {
                let mut damped = jtj;
                for k in 0..6 {
                    damped[(k, k)] *= 1.0 + lambda;
                }
                let Some(delta) = damped.try_inverse().map(|inverse| -(inverse * jtr)) else {
                    break;
                };
                let next: Params = std::array::from_fn(|k| params[k] + delta[k]);
                let next_cost = self.cost(&next);
                if next_cost < cost {
                    let converged = delta.norm() < 1e-9;
                    (params, cost) = (next, next_cost);
                    lambda = (lambda / 10.0).max(1e-9);
                    improved = !converged;
                    break;
                }
                lambda *= 10.0;
            }
            if !improved {
                break;
            }
        }
        params
    }
}

const SWEEP_STEPS: usize = 72;
/// An alternate must explain the corners nearly as well as the primary to be reported.
const MAX_ALTERNATE_ERROR_RATIO: f64 = 3.0;

/// Solves for up to two distinct robot poses that explain the observed corners.
pub fn solve(
    tags: &[TagObservation],
    calibration: &Calibration,
    mount: &Isometry3<f64>,
    image_size: (u32, u32),
) -> Option<Estimate> {
    if tags.is_empty() {
        return None;
    }
    let problem = Problem {
        field: tags.iter().flat_map(|t| t.field.map(|p| p.coords)).collect(),
        image: tags.iter().flat_map(|t| t.pixels.map(|p| undistort(p, calibration))).collect(),
        mount_rotation: OPTICAL * mount.rotation.to_rotation_matrix().matrix().transpose(),
        mount_offset: mount.translation.vector,
        focal: Vector2::new(calibration.fx, calibration.fy),
    };

    let sweep: Vec<(Params, f64)> = (0..SWEEP_STEPS)
        .map(|i| {
            let theta = i as f64 * TAU / SWEEP_STEPS as f64;
            match problem.translation(theta) {
                Some(t) => {
                    let params = [t.x, t.y, 0.0, 0.0, 0.0, theta];
                    (params, problem.cost(&params))
                }
                None => ([0.0, 0.0, 0.0, 0.0, 0.0, theta], f64::INFINITY),
            }
        })
        .collect();
    let mut seeds: Vec<&(Params, f64)> = (0..SWEEP_STEPS)
        .filter(|&i| {
            let cost = sweep[i].1;
            cost.is_finite()
                && cost <= sweep[(i + SWEEP_STEPS - 1) % SWEEP_STEPS].1
                && cost <= sweep[(i + 1) % SWEEP_STEPS].1
        })
        .map(|i| &sweep[i])
        .collect();
    seeds.sort_by(|a, b| a.1.total_cmp(&b.1));

    // (params, cost with the prior, pixel error)
    let mut candidates: Vec<(Params, f64, f64)> = Vec::new();
    for (seed, _) in seeds.into_iter().take(4) {
        let params = problem.refine(*seed);
        let cost = problem.cost(&params);
        if !cost.is_finite() {
            continue;
        }
        let duplicate = candidates.iter().any(|(other, ..)| {
            let distance = (Vector3::from_column_slice(&params[..3])
                - Vector3::from_column_slice(&other[..3]))
            .norm();
            distance < 0.02 && rotation(&params).angle_to(&rotation(other)) < 0.01
        });
        if !duplicate {
            candidates.push((params, cost, problem.pixel_error(&params)));
        }
    }
    candidates.sort_by(|a, b| a.1.total_cmp(&b.1));
    let to_candidate = |(params, _, error): &(Params, f64, f64)| Candidate {
        pose: Isometry3::from_parts(
            Vector3::new(params[0], params[1], params[2]).into(),
            rotation(params),
        ),
        error: *error,
    };
    let primary = to_candidate(candidates.first()?);
    let alternate = candidates
        .get(1)
        .filter(|(.., error)| *error <= MAX_ALTERNATE_ERROR_RATIO * primary.error.max(1.0))
        .map(to_candidate);

    let camera = primary.pose * mount;
    let average_tag_distance = tags
        .iter()
        .map(|t| {
            let center = t.field.iter().map(|p| p.coords).sum::<Vector3<f64>>() / 4.0;
            (center - camera.translation.vector).norm()
        })
        .sum::<f64>()
        / tags.len() as f64;
    let area: f64 = tags
        .iter()
        .map(|t| {
            let p = t.pixels;
            (0..4)
                .map(|i| p[i][0] * p[(i + 1) % 4][1] - p[(i + 1) % 4][0] * p[i][1])
                .sum::<f64>()
                .abs()
                / 2.0
        })
        .sum();
    let tag_ids = tags.iter().filter(|t| t.id < 64).fold(0i64, |bits, t| bits | 1 << t.id);
    Some(Estimate {
        primary,
        alternate,
        tag_ids,
        average_tag_distance,
        tag_area: area / (image_size.0 as f64 * image_size.1 as f64),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn calibration() -> Calibration {
        Calibration {
            fx: 900.0,
            fy: 900.0,
            cx: 640.0,
            cy: 400.0,
            distortion: [-0.1, 0.03, 0.001, -0.002, 0.0],
            rms: None,
        }
    }

    /// Projects field points with OpenCV's distortion model.
    fn project(point: &Point3<f64>, camera: &Isometry3<f64>, k: &Calibration) -> [f64; 2] {
        let o = OPTICAL * (camera.inverse() * point).coords;
        let (x, y) = (o.x / o.z, o.y / o.z);
        let [k1, k2, p1, p2, k3] = k.distortion;
        let r2 = x * x + y * y;
        let radial = 1.0 + r2 * (k1 + r2 * (k2 + r2 * k3));
        let xd = x * radial + 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x);
        let yd = y * radial + p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y;
        [k.fx * xd + k.cx, k.fy * yd + k.cy]
    }

    fn observe(id: u32, tag: Isometry3<f64>, camera: &Isometry3<f64>) -> TagObservation {
        let field = tag_corners(&tag, TAG_SIZE);
        TagObservation { id, pixels: field.map(|p| project(&p, camera, &calibration())), field }
    }

    fn facing(x: f64, y: f64, z: f64, yaw_deg: f64) -> Isometry3<f64> {
        Isometry3::from_parts(
            Vector3::new(x, y, z).into(),
            UnitQuaternion::from_euler_angles(0.0, 0.0, yaw_deg.to_radians()),
        )
    }

    #[test]
    fn recovers_tilted_raised_robot_pose_from_tags_at_several_heights() {
        let mount =
            crate::config::Mount { x: 0.25, y: -0.1, z: 0.4, roll: 2.0, pitch: -12.0, yaw: 15.0 }
                .isometry();
        let robot = Isometry3::from_parts(
            Vector3::new(3.2, 1.7, 0.08).into(),
            UnitQuaternion::from_euler_angles(
                4f64.to_radians(),
                -6f64.to_radians(),
                160f64.to_radians(),
            ),
        );
        let camera = robot * mount;
        let tags = [
            observe(3, facing(0.0, 2.0, 1.2, 0.0), &camera),
            observe(4, facing(0.0, 1.0, 0.45, 0.0), &camera),
            observe(7, facing(0.5, 3.5, 0.4, -60.0), &camera),
        ];
        let estimate = solve(&tags, &calibration(), &mount, (1280, 800)).unwrap();
        // The floor prior pulls slightly toward flat, but close tags at several heights win.
        let error = estimate.primary.pose.inverse() * robot;
        assert!(error.translation.vector.norm() < 0.01, "{:?}", estimate.primary);
        assert!(error.rotation.angle() < 0.5f64.to_radians());
        assert!(estimate.primary.error < 0.1);
        assert_eq!(estimate.tag_ids, 1 << 3 | 1 << 4 | 1 << 7);
    }

    /// A real frame with the robot flat under the trench, seeing two ~19 px tags 4 m away. Without
    /// the floor prior the best pixel fit was 0.8 m underground and pitched 10°.
    #[test]
    fn far_coplanar_tags_stay_on_the_floor() {
        let calibration = Calibration {
            fx: 485.22714440524544,
            fy: 485.2050152053196,
            cx: 324.50469689213844,
            cy: 207.89836185791006,
            distortion: [
                -0.09948349064143425,
                0.13412293525870608,
                -0.00017105212871407996,
                -0.00030704710075745117,
                -0.11360614859723724,
            ],
            rms: None,
        };
        let mount = crate::config::Mount {
            x: -0.318389,
            y: 0.08255,
            z: 0.342468,
            pitch: -20.0,
            yaw: 180.0,
            ..Default::default()
        }
        .isometry();
        let tag = |id, y, pixels| TagObservation {
            id,
            pixels,
            field: tag_corners(&Isometry3::translation(0.007747, y, 0.55245), 0.1651),
        };
        let tags = [
            tag(
                29,
                0.6659626,
                [
                    [313.7897644042969, 366.0027770996092],
                    [332.9158325195313, 366.0675964355469],
                    [333.40338134765625, 346.87905883789074],
                    [314.0379943847656, 346.49871826171875],
                ],
            ),
            tag(
                30,
                1.0977626,
                [
                    [365.49176025390625, 366.7007141113281],
                    [384.98632812499994, 366.7386779785156],
                    [384.40216064453125, 346.83721923828125],
                    [365.1754455566407, 346.60433959960943],
                ],
            ),
        ];
        let primary = solve(&tags, &calibration, &mount, (640, 480)).unwrap().primary;
        let (roll, pitch, _) = primary.pose.rotation.euler_angles();
        assert!(primary.pose.translation.z.abs() < 0.1, "{primary:?}");
        assert!(roll.abs().max(pitch.abs()) < 2f64.to_radians(), "{primary:?}");
    }

    #[test]
    fn single_distant_tag_returns_the_truth_as_a_candidate() {
        let mount = crate::config::Mount { z: 0.5, pitch: -20.0, ..Default::default() }.isometry();
        let robot = facing(5.0, 0.4, 0.0, 175.0);
        let camera = robot * mount;
        let tags = [observe(1, facing(0.0, 0.0, 1.4, 0.0), &camera)];
        let estimate = solve(&tags, &calibration(), &mount, (1280, 800)).unwrap();
        let close = |c: &Candidate| (c.pose.inverse() * robot).translation.vector.norm() < 1e-4;
        assert!(close(&estimate.primary) || estimate.alternate.as_ref().is_some_and(close));
    }
}
