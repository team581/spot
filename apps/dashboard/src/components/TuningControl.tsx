import type { ChangeEvent } from 'react';
import { useDashboard } from '../dashboard';
import type { Camera, Control } from '../types';
import type { LiveTuner } from '../state/editing';
export function TuningControl({ control: c, tuner, camera }: { control: Control; tuner: LiveTuner; camera: Camera }) {
	const { status } = useDashboard();
	const disabled = Boolean(status.lock_reason || !c.allowed || !camera.connected || tuner.history.conflict);
	const value = tuner.gesture ? (tuner.requested[c.name] ?? c.value) : c.value;
	const common = {
		id: 'control-' + c.name,
		disabled,
		value,
		'aria-label': c.label,
		onPointerDown: () => tuner.begin(),
		onPointerUp: () => tuner.end(),
		onPointerCancel: () => tuner.end(),
		onKeyDown: () => tuner.begin(),
		onKeyUp: () => tuner.end(),
		onBlur: () => tuner.end(),
	};
	const request = (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
		tuner.request(c.name, Number(e.target.value), Boolean(c.options?.length));
	return (
		<div className="control" data-control={c.name}>
			<div className="control-heading">
				<label htmlFor={'control-' + c.name}>{c.label}</label>
				<output>
					{value} {c.unit || ''}
				</output>
			</div>
			{c.options?.length ? (
				<select {...common} onChange={request}>
					{c.options.map((o) => (
						<option key={o.value} value={o.value * c.factor}>
							{o.label}
						</option>
					))}
				</select>
			) : (
				<>
					<input
						{...common}
						type="range"
						min={c.min}
						max={c.max}
						step={c.step}
						onChange={request}
						title={c.hardware_max != null ? `${c.range_reason}. Driver maximum: ${c.hardware_max} ${c.unit}.` : ''}
					/>
					<div className="range-labels">
						<span>
							{c.min} {c.unit}
						</span>
						<span>
							{c.max} {c.unit}
						</span>
					</div>
				</>
			)}
			<div className="readback">
				{tuner.inFlight || tuner.pending ? 'Requested · readback' : 'Readback'} {c.value} {c.unit || ''}
			</div>
			<small className="capability-lock">{c.allowed ? c.range_reason || '' : c.reason || 'Unavailable'}</small>
		</div>
	);
}
