import { Check, TriangleAlert } from 'lucide-react';
import { cn } from 'cn';

type StepState = 'complete' | 'current' | 'upcoming' | 'warning';
export interface Step {
	label: string;
	detail?: string;
	state: StepState;
}

const marker: Record<StepState, string> = {
	complete: 'border-success bg-success text-background',
	current: 'border-foreground bg-foreground text-background',
	upcoming: 'border-border text-muted-foreground',
	warning: 'border-warning text-warning',
};

/** A left-to-right progression that marks where something is and what comes next. */
export function Steps({ steps }: { steps: Step[] }) {
	return (
		<ol className="flex flex-col gap-3 sm:flex-row sm:gap-0">
			{steps.map((step, index) => {
				const next = steps[index + 1];
				return (
					<li
						key={step.label}
						data-state={step.state}
						className="flex gap-3 sm:flex-1 sm:flex-col sm:gap-2 sm:last:flex-none"
					>
						<div className="flex items-center">
							<span
								className={cn(
									'flex size-7 shrink-0 items-center justify-center rounded-full border-2 text-xs font-semibold',
									marker[step.state],
								)}
							>
								{step.state === 'complete' ? (
									<Check className="size-4" />
								) : step.state === 'warning' ? (
									<TriangleAlert className="size-3.5" />
								) : (
									index + 1
								)}
							</span>
							{next ? (
								// A segment is filled once the step it leads to has been reached.
								<span
									className={cn(
										'mx-2 hidden h-0.5 flex-1 rounded-full sm:block',
										next.state === 'complete' || next.state === 'warning' ? 'bg-success' : 'bg-border',
									)}
								/>
							) : null}
						</div>
						<div className="flex flex-col sm:pr-4">
							<span className={cn('text-sm font-medium', step.state === 'upcoming' && 'text-muted-foreground')}>
								{step.label}
							</span>
							{step.detail ? <span className="text-xs text-muted-foreground">{step.detail}</span> : null}
						</div>
					</li>
				);
			})}
		</ol>
	);
}
