import type { ReactNode } from 'react';
import { CircleCheck, TriangleAlert } from 'lucide-react';
import { cn } from 'cn';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
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
/** Save a JSON document through the browser's download prompt. */
export function saveJson(value: unknown, name: string) {
	const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + '\n'], { type: 'application/json' }));
	const link = document.createElement('a');
	link.href = url;
	link.download = name;
	link.click();
	setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function PageTitle({ children, id }: { children: ReactNode; id?: string }) {
	return (
		<h1 id={id} className="font-heading text-2xl font-semibold">
			{children}
		</h1>
	);
}
export function Panel({
	title,
	action,
	className,
	children,
}: {
	title?: ReactNode;
	action?: ReactNode;
	className?: string;
	children: ReactNode;
}) {
	return (
		<Card className={cn('min-w-0', className)}>
			{title ? (
				<CardHeader>
					<CardTitle role="heading" aria-level={2} className="text-base">
						{title}
					</CardTitle>
					{action ? <CardAction>{action}</CardAction> : null}
				</CardHeader>
			) : null}
			<CardContent className="flex flex-col gap-3">{children}</CardContent>
		</Card>
	);
}
/** Status text for locks and failures. Empty messages take no space. */
export function Feedback({ children, id, className }: { children?: ReactNode; id?: string; className?: string }) {
	return (
		<p id={id} role="status" className={cn('text-xs whitespace-pre-wrap text-warning empty:hidden', className)}>
			{children}
		</p>
	);
}
export function DataList({ values, id }: { values: Record<string, string | number>; id?: string }) {
	return (
		<dl className="grid grid-cols-[40%_minmax(0,1fr)] gap-x-3 gap-y-3 max-sm:grid-cols-1 max-sm:gap-y-1" id={id}>
			{Object.entries(values).map(([key, value]) => (
				<div className="contents" key={key}>
					<dt className="text-muted-foreground">{key}</dt>
					<dd className="wrap-anywhere max-sm:mb-2">{value}</dd>
				</div>
			))}
		</dl>
	);
}
export function CalibrationState({ camera: c }: { camera: Camera }) {
	return c.health === 'Disabled' ? (
		<span className="text-xs text-muted-foreground">Disabled in code</span>
	) : !c.logical_name ? (
		<span className="inline-flex items-center gap-1 text-xs text-warning">
			<TriangleAlert className="size-3.5" aria-hidden /> Choose camera name
		</span>
	) : c.calibrated ? (
		<span className="inline-flex items-center gap-1 text-xs text-success">
			<CircleCheck className="size-3.5" aria-hidden /> Calibrated
		</span>
	) : (
		<span className="inline-flex items-center gap-1 text-xs text-warning">
			<TriangleAlert className="size-3.5" aria-hidden /> Calibration required
		</span>
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
		<NativeSelect
			className="w-full lg:hidden"
			aria-label="Select camera"
			value={id}
			onChange={(e) => {
				location.hash = 'camera/' + encodeURIComponent(e.target.value) + (geometry ? '/geometry' : '');
			}}
		>
			{cameras.map((c) => (
				<NativeSelectOption key={c.identity} value={c.identity}>
					{c.name}
				</NativeSelectOption>
			))}
		</NativeSelect>
	);
}
/** Hash-routed tabs styled like shadcn's tab list. */
export function LinkTabs({
	tabs,
	children,
}: {
	tabs: { href: string; label: string; active: boolean }[];
	children?: ReactNode;
}) {
	return (
		<div className="flex flex-wrap items-center gap-2">
			<nav className="inline-flex rounded-lg bg-muted p-0.5">
				{tabs.map((tab) => (
					<a
						key={tab.href}
						href={tab.href}
						aria-current={tab.active ? 'page' : undefined}
						className="rounded-md px-3 py-1 text-xs font-medium text-muted-foreground hover:text-foreground aria-[current=page]:bg-background aria-[current=page]:text-foreground aria-[current=page]:shadow-sm"
					>
						{tab.label}
					</a>
				))}
			</nav>
			{children ? <div className="ml-auto flex gap-2">{children}</div> : null}
		</div>
	);
}
export function CameraTabs({ id, geometry = false }: { id: string; geometry?: boolean }) {
	const href = '#camera/' + encodeURIComponent(id);
	return (
		<LinkTabs
			tabs={[
				{ href, label: 'Camera', active: !geometry },
				{ href: href + '/geometry', label: 'Geometry', active: geometry },
			]}
		/>
	);
}
