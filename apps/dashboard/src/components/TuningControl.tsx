import { useStatus } from '../queries';
import type { Camera, Control } from '../types';
import type { LiveTuner } from '../state/editing';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Slider } from '@/components/ui/slider';
export function TuningControl({ control: c, tuner, camera }: { control: Control; tuner: LiveTuner; camera: Camera }) {
	const status = useStatus();
	const disabled = Boolean(status.lock_reason || !c.allowed || !camera.connected || tuner.history.conflict);
	const value = tuner.gesture ? (tuner.requested[c.name] ?? c.value) : c.value;
	const id = 'control-' + c.name;
	const gesture = {
		onPointerDown: () => tuner.begin(),
		onPointerUp: () => tuner.end(),
		onPointerCancel: () => tuner.end(),
		onKeyDown: () => tuner.begin(),
		onKeyUp: () => tuner.end(),
		onBlur: () => tuner.end(),
	};
	return (
		<div className="flex flex-col gap-2" data-control={c.name}>
			<div className="flex items-center justify-between gap-2">
				<Label id={id + '-label'} htmlFor={c.options?.length ? id : undefined}>
					{c.label}
				</Label>
				<output className="min-w-18 rounded-md border bg-muted px-2 py-0.5 text-center text-xs whitespace-nowrap">
					{value} {c.unit || ''}
				</output>
			</div>
			{c.options?.length ? (
				<NativeSelect
					{...gesture}
					id={id}
					className="w-full"
					disabled={disabled}
					value={value}
					onChange={(e) => tuner.request(c.name, Number(e.target.value), true)}
				>
					{c.options.map((o) => (
						<NativeSelectOption key={o.value} value={o.value * c.factor}>
							{o.label}
						</NativeSelectOption>
					))}
				</NativeSelect>
			) : (
				<>
					<Slider
						{...gesture}
						aria-labelledby={id + '-label'}
						disabled={disabled}
						value={[value]}
						min={c.min}
						max={c.max}
						step={c.step}
						onValueChange={(next) => tuner.request(c.name, Array.isArray(next) ? next[0] : next)}
						onValueCommitted={() => tuner.end()}
						title={c.hardware_max != null ? `${c.range_reason}. Driver maximum: ${c.hardware_max} ${c.unit}.` : ''}
					/>
					<div className="flex justify-between text-xs text-muted-foreground">
						<span>
							{c.min} {c.unit}
						</span>
						<span>
							{c.max} {c.unit}
						</span>
					</div>
				</>
			)}
			<div className="readback min-h-4 text-xs">
				{tuner.inFlight || tuner.pending ? 'Requested · readback' : 'Readback'} {c.value} {c.unit || ''}
			</div>
			<small className="text-xs text-muted-foreground empty:hidden">
				{c.allowed ? c.range_reason || '' : c.reason || 'Unavailable'}
			</small>
		</div>
	);
}
