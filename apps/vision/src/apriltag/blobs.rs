//! Tag candidates from the dark-sample masks: runs joined into blobs, and a rough
//! quadrilateral for each blob with a tag's size, shape, and fill.

use super::dense::Level;
use super::geometry::Vec2;

#[derive(Clone, Copy)]
struct Run {
    y: u16,
    x0: u16,
    /// Exclusive.
    x1: u16,
}

fn find(parent: &mut [u32], mut i: u32) -> u32 {
    while parent[i as usize] != i {
        let p = parent[i as usize];
        parent[i as usize] = parent[p as usize];
        i = p;
    }
    i
}

#[derive(Clone, Copy)]
struct Blob {
    /// Index in `Scratch::groups`, or `u32::MAX`.
    slot: u32,
    count: u32,
    runs: u32,
    links: u32,
    x0: u16,
    x1: u16,
    y0: u16,
    y1: u16,
}

/// A rough quadrilateral, clockwise in image coordinates, in pixels.
pub struct Candidate {
    pub corners: [Vec2; 4],
    /// The level's sample spacing, which bounds how far the rough corners may be off.
    pub step: f32,
    /// Whether the level averages pixels, which rounds off corners.
    pub averaged: bool,
}

#[derive(Default)]
pub struct Scratch {
    runs: Vec<Run>,
    parent: Vec<u32>,
    /// Overlaps with the previous row's runs, per run.
    links: Vec<u32>,
    blobs: Vec<Blob>,
    points: Vec<Vec2>,
    /// Plausible blobs: root run, and the end of its runs in `order`.
    groups: Vec<(u32, u32)>,
    next: Vec<u32>,
    order: Vec<u32>,
}

/// Appends the runs of set bits in one mask row.
fn row_runs(words: &[u32], y: u16, runs: &mut Vec<Run>) {
    let mut start = 0;
    let mut in_run = false;
    for (i, &word) in words.iter().enumerate() {
        let base = i as u32 * 32;
        let mut v = word as u64;
        let mut pos = 0;
        while pos < 32 {
            if in_run {
                // Bits past the word are clear in `v`, so this stops at the word's end.
                let ones = (!v).trailing_zeros();
                pos += ones;
                v >>= ones;
                if pos < 32 {
                    runs.push(Run { y, x0: start as u16, x1: (base + pos) as u16 });
                    in_run = false;
                }
            } else {
                if v == 0 {
                    break;
                }
                let zeros = v.trailing_zeros();
                pos += zeros;
                v >>= zeros;
                start = base + pos;
                in_run = true;
            }
        }
    }
    if in_run {
        runs.push(Run { y, x0: start as u16, x1: (words.len() * 32) as u16 });
    }
}

/// Finds rough quadrilaterals for dark blobs of tag-like size and shape in one level.
pub fn candidates(level: &Level, mask: &[u32], scratch: &mut Scratch, out: &mut Vec<Candidate>) {
    let (words, h) = (level.words(), level.height);
    let s = scratch;
    // Runs of dark samples, joined across rows (8-connected) with union-find.
    s.runs.clear();
    s.parent.clear();
    s.links.clear();
    let mut previous = 0..0;
    for y in 0..h {
        let current_start = s.runs.len();
        row_runs(&mask[y * words..(y + 1) * words], y as u16, &mut s.runs);
        let current = current_start..s.runs.len();
        // Two-pointer overlap between this row's runs and the previous row's.
        let mut p = previous.start;
        for i in current.clone() {
            let r = s.runs[i];
            while p < previous.end && s.runs[p].x1 < r.x0 {
                p += 1;
            }
            // A new run joins its first overlap's root directly, which keeps trees shallow.
            let mut root = i as u32;
            let mut q = p;
            let mut links = 0;
            while q < previous.end && s.runs[q].x0 <= r.x1 {
                let other = find(&mut s.parent, q as u32);
                if links == 0 {
                    root = other;
                } else if other != root {
                    let (lo, hi) = if other < root { (other, root) } else { (root, other) };
                    s.parent[hi as usize] = lo;
                    root = lo;
                }
                links += 1;
                q += 1;
            }
            s.parent.push(root);
            s.links.push(links);
        }
        previous = current;
    }
    // Blob statistics per root.
    let n = s.runs.len();
    s.blobs.clear();
    s.blobs.resize(
        n,
        Blob {
            slot: u32::MAX,
            count: 0,
            runs: 0,
            links: 0,
            x0: u16::MAX,
            x1: 0,
            y0: u16::MAX,
            y1: 0,
        },
    );
    for i in 0..n {
        let root = find(&mut s.parent, i as u32) as usize;
        s.parent[i] = root as u32;
        let r = s.runs[i];
        let b = &mut s.blobs[root];
        b.count += (r.x1 - r.x0) as u32;
        b.runs += 1;
        b.links += s.links[i];
        b.x0 = b.x0.min(r.x0);
        b.x1 = b.x1.max(r.x1);
        b.y0 = b.y0.min(r.y);
        b.y1 = b.y1.max(r.y + 1);
    }

    // Runs of each plausible blob, grouped by blob in row order (a counting sort).
    s.groups.clear();
    for i in 0..n {
        let b = &mut s.blobs[i];
        if s.parent[i] as usize != i {
            continue;
        }
        let extent = (b.x1 - b.x0).max(b.y1 - b.y0) as usize;
        let narrow = (b.x1 - b.x0).min(b.y1 - b.y0) as usize;
        if (level.min_extent..=level.max_extent).contains(&extent)
            && narrow >= 3
            && b.count >= 8
            // The border encloses white cells: the run graph has a cycle.
            && b.links + 1 > b.runs
        {
            b.slot = s.groups.len() as u32;
            let start = s.groups.last().map_or(0, |&(_, end)| end);
            s.groups.push((i as u32, start));
            s.groups.last_mut().unwrap().1 += b.runs;
        }
    }
    s.order.clear();
    s.order.resize(s.groups.last().map_or(0, |g| g.1) as usize, 0);
    s.next.clear();
    s.next.extend(s.groups.iter().map(|&(root, end)| end - s.blobs[root as usize].runs));
    for i in 0..n {
        let slot = s.blobs[s.parent[i] as usize].slot;
        if slot != u32::MAX {
            let at = &mut s.next[slot as usize];
            s.order[*at as usize] = i as u32;
            *at += 1;
        }
    }

    let mut start = 0;
    for &(root, end) in &s.groups {
        let group = &s.order[start as usize..end as usize];
        start = end;
        // The outline: each row's outermost samples.
        s.points.clear();
        let (mut sx, mut sy) = (0f32, 0f32);
        let mut row = (u16::MAX, 0, 0);
        for &i in group {
            let r = s.runs[i as usize];
            let len = (r.x1 - r.x0) as f32;
            sx += len * (r.x0 as f32 + r.x1 as f32 - 1.0) / 2.0;
            sy += len * r.y as f32;
            if r.y != row.0 {
                if row.0 != u16::MAX {
                    s.points.push(Vec2::new(row.1 as f32, row.0 as f32));
                    s.points.push(Vec2::new((row.2 - 1) as f32, row.0 as f32));
                }
                row = (r.y, r.x0, r.x1);
            } else {
                row.2 = r.x1;
            }
        }
        s.points.push(Vec2::new(row.1 as f32, row.0 as f32));
        s.points.push(Vec2::new((row.2 - 1) as f32, row.0 as f32));
        let blob = s.blobs[root as usize];
        let centroid = Vec2::new(sx, sy) * (1.0 / blob.count as f32);
        let q = rough_quad(&s.points, centroid, blob.count as f32);
        if let Ok(quad) = q {
            out.push(Candidate {
                corners: quad.map(|p| level.pixel(p.x, p.y)),
                step: level.step,
                averaged: level.averaged,
            });
        }
    }
}

/// Corners of a blob's outline from its extreme points, if the blob is shaped like a tag.
fn rough_quad(points: &[Vec2], centroid: Vec2, count: f32) -> Result<[Vec2; 4], String> {
    let distance = |p: &Vec2, from: Vec2| (*p - from).dot(*p - from);
    // The point farthest from the centroid is a corner, and the opposite corner is near its
    // reflection through the centroid. (Under steep perspective a side can be longer than a
    // diagonal, so the point farthest from a corner may be its neighbour.)
    let a = *points
        .iter()
        .max_by(|p, q| distance(p, centroid).total_cmp(&distance(q, centroid)))
        .ok_or("empty")?;
    let mirror = centroid * 2.0 - a;
    let c = *points
        .iter()
        .min_by(|p, q| distance(p, mirror).total_cmp(&distance(q, mirror)))
        .ok_or("empty")?;
    let axis = c - a;
    let (mut b, mut d) = (a, a);
    let (mut b_dist, mut d_dist) = (0.0f32, 0.0f32);
    for &p in points {
        let dist = axis.cross(p - a);
        if dist > b_dist {
            (b, b_dist) = (p, dist);
        }
        if dist < d_dist {
            (d, d_dist) = (p, dist);
        }
    }
    let diagonal = axis.length();
    // Both other corners must lie well off the diagonal.
    if b_dist < 0.15 * diagonal * diagonal || -d_dist < 0.15 * diagonal * diagonal {
        return Err(format!("diagonal {} {}", b_dist / diagonal, d_dist / diagonal));
    }
    // a, b, c, d run counterclockwise or clockwise; make them clockwise (y down).
    let mut quad = [a, b, c, d];
    if (0..4).map(|i| quad[i].cross(quad[(i + 1) % 4])).sum::<f32>() < 0.0 {
        quad.swap(1, 3);
    }
    // Each corner is the outline point farthest outside the line between its neighbours.
    for _ in 0..2 {
        for i in 0..4 {
            let (prev, next) = (quad[(i + 3) % 4], quad[(i + 1) % 4]);
            let across = next - prev;
            // Clockwise, the outside of prev -> next is where the cross product is negative.
            quad[i] = *points
                .iter()
                .min_by(|p, q| across.cross(**p - prev).total_cmp(&across.cross(**q - prev)))
                .ok_or("empty")?;
        }
    }
    let area = 0.5 * (0..4).map(|i| quad[i].cross(quad[(i + 1) % 4])).sum::<f32>();
    // Sample centres sit half a sample inside the outline.
    let area = area.abs() + diagonal;
    // The border alone is 28 of 64 cells. A faint tag on a bright background can read dark
    // throughout, margin included.
    let fill = count / area;
    if !(0.25..=1.2).contains(&fill) {
        return Err(format!("fill {fill}"));
    }
    let sides = (0..4).map(|i| (quad[(i + 1) % 4] - quad[i]).length());
    let (lo, hi) = sides.fold((f32::MAX, 0f32), |(lo, hi), s| (lo.min(s), hi.max(s)));
    if lo < 0.25 * hi {
        return Err(format!("sides {lo} {hi}"));
    }
    // A tag's outline stays near its quad; curved shapes such as letters bulge past it.
    let tolerance = (0.1 * (lo + hi) / 2.0).max(1.5);
    let normals = std::array::from_fn::<_, 4, _>(|i| {
        let side = quad[(i + 1) % 4] - quad[i];
        Vec2::new(side.y, -side.x) * (1.0 / side.length())
    });
    let outside =
        points.iter().filter(|&&p| (0..4).any(|i| normals[i].dot(p - quad[i]) > tolerance)).count();
    if outside * 20 <= points.len() {
        Ok(quad)
    } else {
        Err(format!("bulge {outside}/{}", points.len()))
    }
}
