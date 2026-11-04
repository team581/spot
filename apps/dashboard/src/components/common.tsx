import type { Camera } from '../types';
export const fmt = (value: number | undefined, digits = 1) => (Number.isFinite(value) ? value!.toFixed(digits) : '—');
export const age = (value: number | undefined) =>
	!Number.isFinite(value) ? '— ms' : value! < 1 ? `${Math.round(value! * 1000)} ms` : `${value!.toFixed(1)} s`;
export const date = (value: string | undefined) =>
	value && !Number.isNaN(Date.parse(value))
		? new Date(value).toLocaleString(undefined, {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit',
				hour12: false,
			})
		: 'Time unavailable';
const paths: Record<string, string> = {
	overview: 'M3 10 10 4l7 6v10h-5v-6H8v6H3Z',
	cameras: 'M3 7h4l2-3h5l2 3h3v13H3ZM15 13a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
	calibration: 'M5 3v4H2v10h3v4M15 3v4h3v10h-3v4M5 12h10M10 7v10',
	network: 'M6 2v5h8V2M10 7v6M3 13h14v6H3M10 19v3',
	system: 'M3 4h15v5H3ZM3 14h15v5H3ZM6 6.5h1M6 16.5h1M13 6.5h2M13 16.5h2',
	docs: 'M10 5C7 3 4 3 2 4v15c3-1 5-1 8 1 3-2 5-2 8-1V4c-3-1-5-1-8 1Zm0 0v15',
	Auto: 'M2 3h17v12H2ZM10 15v5M6 20h8',
	Light: 'M10 6a4 4 0 1 1 0 8 4 4 0 0 1 0-8M10 1v2M10 17v2M1 10h2M17 10h2M3 3l2 2M15 15l2 2M3 17l2-2M15 5l2-2',
	Dark: 'M18 13A8 8 0 0 1 7 2 8 8 0 1 0 18 13',
	undo: 'M7 4 3 8l4 4M3 8h8a6 6 0 0 1 6 6',
	redo: 'm13 4 4 4-4 4M17 8H9a6 6 0 0 0-6 6',
};
export function Icon({ name }: { name: string }) {
	return (
		<svg className="icon" viewBox="0 0 22 24" aria-hidden="true">
			<path d={paths[name] || paths.cameras} />
		</svg>
	);
}
export function DataList({ values, id }: { values: Record<string, string | number>; id?: string }) {
	return (
		<dl className="data-list" id={id}>
			{Object.entries(values).map(([key, value]) => (
				<div className="data-row" key={key}>
					<dt>{key}</dt>
					<dd>{value}</dd>
				</div>
			))}
		</dl>
	);
}
export function WarningLink({ camera: c }: { camera: Camera }) {
	return c.health === 'Disabled' ? (
		<span className="calibrated">Disabled in code</span>
	) : c.calibrated ? (
		<span className="calibrated good">✓ calibrated</span>
	) : (
		<a className="calibrated warning" href="#calibration">
			⚠ Calibration required
		</a>
	);
}
export function CameraSelector({
	cameras,
	id,
	geometry = false,
}: {
	cameras: Camera[];
	id: string;
	geometry?: boolean;
}) {
	return (
		<select
			className="camera-selector"
			aria-label="Select camera"
			value={id}
			onChange={(e) => {
				location.hash = 'camera/' + encodeURIComponent(e.target.value) + (geometry ? '/geometry' : '');
			}}
		>
			{cameras.map((c) => (
				<option key={c.identity} value={c.identity}>
					{c.name}
				</option>
			))}
		</select>
	);
}
export function CameraTabs({ id, geometry = false }: { id: string; geometry?: boolean }) {
	return (
		<div className="tabs">
			<a href={'#camera/' + encodeURIComponent(id)} className={!geometry ? 'active' : ''}>
				Camera
			</a>
			<a href={'#camera/' + encodeURIComponent(id) + '/geometry'} className={geometry ? 'active' : ''}>
				Geometry
			</a>
		</div>
	);
}
