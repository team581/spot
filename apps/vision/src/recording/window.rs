//! When to record: from before each enable until after the robot disables, while synced with NT
//! server time.

const PREROLL_US: i64 = 5_000_000;
const POSTROLL_US: i64 = 5_000_000;
const ENABLED: i64 = 0x01;
const FMS_ATTACHED: i64 = 0x10;

/// Latest `/FMSInfo` values.
#[derive(Debug, Clone, Default)]
pub struct Fms {
    pub control: i64,
    pub event: String,
    pub match_type: i64,
    pub match_number: i64,
    pub replay: i64,
}

impl Fms {
    /// Updates from an `/FMSInfo/<key>` value.
    pub fn set(&mut self, key: &str, value: &rmpv::Value) {
        // WPILib publishes integers; accept doubles from other clients too.
        let int = || value.as_i64().or(value.as_f64().map(|v| v as i64)).unwrap_or_default();
        match key {
            "FMSControlData" => self.control = int(),
            "EventName" => self.event = value.as_str().unwrap_or_default().to_string(),
            "MatchType" => self.match_type = int(),
            "MatchNumber" => self.match_number = int(),
            "ReplayNumber" => self.replay = int(),
            _ => {}
        }
    }

    /// `EVENT_Q12` when the FMS is attached, otherwise the local time.
    fn recording_name(&self) -> String {
        let kind = match self.match_type {
            1 => "P",
            2 => "Q",
            3 => "E",
            _ => "",
        };
        if self.control & FMS_ATTACHED != 0 && !self.event.is_empty() && !kind.is_empty() {
            let event: String =
                self.event.chars().filter(|c| c.is_ascii_alphanumeric() || *c == '-').collect();
            let replay = if self.replay > 1 { format!("_R{}", self.replay) } else { String::new() };
            format!("{event}_{kind}{}{replay}", self.match_number)
        } else {
            local_time()
        }
    }
}

fn local_time() -> String {
    // SAFETY: `time` accepts null, and `tm` is written by localtime_r before it is read.
    let tm = unsafe {
        let now = libc::time(std::ptr::null_mut());
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&now, &mut tm);
        tm
    };
    format!(
        "{:04}-{:02}-{:02}_{:02}-{:02}-{:02}",
        tm.tm_year + 1900,
        tm.tm_mon + 1,
        tm.tm_mday,
        tm.tm_hour,
        tm.tm_min,
        tm.tm_sec
    )
}

/// A recording to save from the buffered segments.
#[derive(Debug, PartialEq)]
pub struct Finish {
    pub start_us: i64,
    pub end_us: i64,
    pub name: String,
}

/// Log times switched to another time base after `end_us`.
#[derive(Debug, PartialEq)]
pub struct Restart {
    pub end_us: i64,
    /// The recording in progress, finished with the old time base.
    pub finish: Option<Finish>,
}

/// What the recorder should do this tick, in order.
#[derive(Debug, PartialEq)]
pub struct Decision {
    /// Save any recording in progress, then discard every buffered segment.
    pub restart: Option<Restart>,
    /// Save a recording once the current segment is rotated.
    pub finish: Option<Finish>,
    /// Buffered segments ending before this are no longer needed.
    pub keep_from_us: i64,
}

struct Active {
    start_us: i64,
    name: String,
    disabled_us: Option<i64>,
}

#[derive(Default)]
pub struct Window {
    synced: bool,
    last_us: i64,
    active: Option<Active>,
}

impl Window {
    /// `recording` is whether there is a config to record with.
    pub fn tick(&mut self, now_us: i64, synced: bool, recording: bool, fms: &Fms) -> Decision {
        let mut restart = None;
        if synced != self.synced {
            let end_us = self.last_us;
            let finish =
                self.active.take().map(|a| Finish { start_us: a.start_us, end_us, name: a.name });
            restart = Some(Restart { end_us, finish });
            self.synced = synced;
        }
        self.last_us = now_us;
        if !recording {
            self.active = None;
        }

        let enabled = recording && synced && fms.control & ENABLED != 0;
        let mut finish = None;
        match &mut self.active {
            None if enabled => {
                self.active = Some(Active {
                    start_us: now_us - PREROLL_US,
                    name: fms.recording_name(),
                    disabled_us: None,
                });
            }
            Some(active) if enabled => active.disabled_us = None,
            Some(active) if active.disabled_us.is_none() => active.disabled_us = Some(now_us),
            Some(Active { disabled_us: Some(at), .. }) if now_us - *at >= POSTROLL_US => {
                let active = self.active.take().unwrap();
                finish =
                    Some(Finish { start_us: active.start_us, end_us: now_us, name: active.name });
            }
            _ => {}
        }

        let keep_from_us = self
            .active
            .as_ref()
            .map_or(now_us - PREROLL_US, |a| a.start_us.min(now_us - PREROLL_US));
        Decision { restart, finish, keep_from_us }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const S: i64 = 1_000_000;

    fn fms(control: i64) -> Fms {
        Fms { control, event: "CAVAL".into(), match_type: 2, match_number: 12, replay: 1 }
    }

    /// Ticks once a second while synced, returning the recordings finished.
    fn run(window: &mut Window, from_s: i64, to_s: i64, control: i64) -> Vec<Finish> {
        (from_s..to_s)
            .filter_map(|t| window.tick(t * S, true, true, &fms(control)).finish)
            .collect()
    }

    fn synced_window() -> Window {
        let mut window = Window::default();
        window.tick(0, true, true, &fms(0));
        window
    }

    #[test]
    fn records_from_before_enable_until_after_disable() {
        let mut window = synced_window();
        assert!(run(&mut window, 1, 10, 0).is_empty());
        assert!(run(&mut window, 10, 20, ENABLED | FMS_ATTACHED).is_empty());
        assert!(run(&mut window, 20, 24, FMS_ATTACHED).is_empty());
        // Segments from the pre-roll on are kept while recording.
        assert_eq!(window.tick(24 * S, true, true, &fms(FMS_ATTACHED)).keep_from_us, 5 * S);
        let finished = run(&mut window, 25, 30, FMS_ATTACHED);
        assert_eq!(
            finished,
            [Finish { start_us: 5 * S, end_us: 25 * S, name: "CAVAL_Q12".into() }]
        );
    }

    #[test]
    fn enabling_during_post_roll_continues_the_recording() {
        let mut window = synced_window();
        run(&mut window, 10, 12, ENABLED);
        run(&mut window, 12, 14, 0);
        run(&mut window, 14, 16, ENABLED);
        let finished = run(&mut window, 16, 30, 0);
        assert_eq!(finished.len(), 1);
        assert_eq!((finished[0].start_us, finished[0].end_us), (5 * S, 21 * S));
    }

    #[test]
    fn unsynced_enables_are_not_recorded() {
        let mut window = Window::default();
        for t in 0..30 {
            let control = if (5..10).contains(&t) { ENABLED } else { 0 };
            let decision = window.tick(t * S, false, true, &fms(control));
            assert_eq!(decision.finish, None);
            assert_eq!(decision.restart, None);
        }
    }

    #[test]
    fn losing_sync_finishes_with_the_old_time_base() {
        let mut window = synced_window();
        run(&mut window, 10, 13, ENABLED | FMS_ATTACHED);
        let decision = window.tick(500, false, true, &fms(ENABLED));
        let finish = Finish { start_us: 5 * S, end_us: 12 * S, name: "CAVAL_Q12".into() };
        assert_eq!(decision.restart, Some(Restart { end_us: 12 * S, finish: Some(finish) }));
        assert_eq!(decision.finish, None);
    }

    #[test]
    fn names_recordings_by_match_when_the_fms_is_attached() {
        let replay = Fms { control: FMS_ATTACHED, event: "CA VAL!".into(), replay: 2, ..fms(0) };
        assert_eq!(replay.recording_name(), "CAVAL_Q12_R2");
        let practice = Fms { match_type: 0, ..fms(FMS_ATTACHED) };
        assert!(!practice.recording_name().starts_with("CAVAL"));
        assert!(!fms(0).recording_name().starts_with("CAVAL"));
    }
}
