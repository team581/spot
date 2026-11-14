import type { ReactNode } from 'react';
import { cn } from 'cn';
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { CameraState } from '../api';

/** Fixed-point text for nullable numbers. */
export const fmt = (value: number | null | undefined, digits = 1) =>
	value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);

export function PageTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
	return (
		<div className="flex flex-wrap items-center justify-between gap-2">
			<h1 className="font-heading text-2xl font-semibold">{children}</h1>
			{action}
		</div>
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
					<CardTitle className="text-base">{title}</CardTitle>
					{action ? <CardAction>{action}</CardAction> : null}
				</CardHeader>
			) : null}
			<CardContent className="flex flex-col gap-3">{children}</CardContent>
		</Card>
	);
}

/** A failure message; renders nothing without one. */
export function ErrorText({ error }: { error: Error | string | null | undefined }) {
	return error ? (
		<p className="text-sm whitespace-pre-wrap text-destructive">{typeof error === 'string' ? error : error.message}</p>
	) : null;
}

export const stateLabel = (state: string) => (state[0]?.toUpperCase() + state.slice(1)).replaceAll('_', ' ');

export function StateBadge({ state }: { state: CameraState }) {
	return (
		<span
			className={cn(
				'rounded-full border px-2 py-0.5 text-xs font-medium',
				state === 'streaming' ? 'border-success/40 text-success' : 'border-warning/40 text-warning',
			)}
		>
			{stateLabel(state)}
		</span>
	);
}

/** A commit's date in the viewer's time zone, as `YYYY-MM-DD`. */
export const commitDate = (unixSeconds: number) => new Date(unixSeconds * 1000).toLocaleDateString('en-CA');

/** Links the Git commit Spot was built from, highlighting builds with uncommitted changes. */
export function Revision({ revision }: { revision: string }) {
	const dirty = revision.endsWith('-dirty');
	return (
		<a
			href={`https://github.com/team581/spot/commit/${revision.replace(/-dirty$/, '')}`}
			target="_blank"
			rel="noreferrer"
			title={dirty ? 'Built with uncommitted changes' : undefined}
			className={cn('font-mono underline-offset-4 hover:underline', dirty && 'text-warning')}
		>
			{revision}
		</a>
	);
}

export function DataList({ values }: { values: Record<string, ReactNode> }) {
	return (
		<dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
			{Object.entries(values).map(([key, value]) => (
				<div className="contents" key={key}>
					<dt className="text-muted-foreground">{key}</dt>
					<dd className="wrap-anywhere">{value}</dd>
				</div>
			))}
		</dl>
	);
}
