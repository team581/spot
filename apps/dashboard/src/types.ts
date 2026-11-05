/** Snapshot contracts consumed from the installed Python HTTP service. */
export type Values = Record<string, number>;
export interface Geometry {
	translation: number[];
	quaternion: number[];
}
export interface Control {
	name: string;
	label: string;
	value: number;
	min: number;
	max: number;
	step: number;
	factor: number;
	unit: string;
	allowed: boolean;
	required?: boolean;
	reason?: string;
	range_reason?: string;
	hardware_max?: number;
	options?: { value: number; label: string }[];
}
export interface Camera {
	identity: string;
	name: string;
	logical_name?: string | null;
	connected: boolean;
	present?: boolean;
	health?: string;
	calibrated: boolean;
	standalone_setup?: boolean;
	controls?: Control[];
	geometry?: Geometry;
	age_s?: number;
	fault?: string;
	display_id?: string;
	topology?: string;
	capture_node?: string;
	unique_serial?: boolean;
	serial?: string;
	mode_id?: string;
	mode_signature?: string;
	allowed_modes?: {
		id: string;
		width: number;
		height: number;
		fps: number;
		pixel_format: string;
		supported: boolean;
	}[];
	metrics?: {
		fps_capture?: number;
		fps_detect?: number;
		captured?: number;
		detect_age_s?: number;
		published?: number;
		withheld?: number;
		publish_age_s?: number;
		overwritten_before_processing?: number;
		driver_sequence_gaps?: number;
	};
	processing?: {
		backend?: string;
		overload_reduction?: boolean;
	};
}
export interface Frame {
	image?: string;
	sequence: number;
	capture_epoch: string;
	generation: string;
	width: number;
	height: number;
	age_s: number;
	stale: boolean;
	processed: boolean;
	tags: {
		id: number;
		corners: number[][];
		distance_m?: number;
		error_px?: number;
		used?: boolean;
		reason?: string;
	}[];
	candidates?: (Geometry & { error_px?: number; ids?: number[] })[];
}
interface CalibrationSession {
	fit_views: number;
	holdout_views: number;
	running: boolean;
	solving: boolean;
	reason?: string;
	board_detected: boolean;
	fit?: { accepted: boolean; rms_reprojection_error_px?: number; reason?: string };
	holdout?: { accepted: boolean; rms_px?: number };
	coverage?: {
		coverage_progress: number;
		coverage_particles?: { x: number; y: number; progress: number }[];
	};
}
interface Network {
	available?: boolean;
	hostname?: string;
	error?: string;
	addresses?: string[];
	maintenance_address?: string;
	mode?: 'automatic' | 'static';
	address?: string;
	pending?: { token: string; address?: string; remaining_s: number };
}
export interface Status {
	has_overrides?: boolean;
	override_paths?: string[];
	cameras: Camera[];
	names: string[];
	revision: string;
	lock_reason: string;
	applied_generation?: string;
	connected?: boolean;
	fresh?: boolean;
	standalone?: boolean;
	has_configuration?: boolean;
	uptime_s?: number;
	clock: {
		state?: string;
		offset_us?: number;
	};
	software: {
		package_path?: string;
		configuration_revision?: string;
		version?: string;
		native_cuda?: boolean;
		process_started_at?: string;
		system_path?: string;
	};
	calibration: {
		cameras: Record<string, CalibrationSession>;
		board?: Record<string, string | number>;
		options?: Record<string, string | number>;
	};
	history?: {
		generation: string;
		active?: boolean;
		error?: string;
		cameras: { identity: string; mode_signature: string; id: string; saved_at?: string }[];
	}[];
	network?: Network;
	endpoint?: { configured?: string; team?: number; mode?: string; local_addresses?: string[] };
	system?: {
		cpu_percent?: number;
		gpu_percent?: number;
		temperature_c?: number;
		memory_used_gb?: number;
		memory_total_gb?: number;
	};
	startup?: Record<string, number>;
	faults?: string[];
	robot_decisions?: Record<
		string,
		{
			capture_epoch: string;
			sequence: number;
			state: string;
			fusion_enabled: boolean;
			fused: boolean;
		}
	>;
	field?: {
		origin?: string;
		length: number;
		width: number;
		tags: (Geometry & { id: number; size: number })[];
	};
}
export interface Job {
	state: 'pending' | 'rejected' | 'applied';
	error?: string;
	revision: string;
	controls?: Values;
	applied_generation?: string;
}
export type Mutate = (operation: string, payload: Record<string, unknown>) => Promise<Job>;
export const initialStatus: Status = {
	cameras: [],
	names: [],
	revision: '',
	lock_reason: 'Robot state unknown · locked',
	clock: {},
	software: {},
	calibration: { cameras: {} },
};
