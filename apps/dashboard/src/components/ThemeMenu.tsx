import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { theme } from '../theme';
import type { Preference } from '../state/theme';
import { Icon } from './common';
export function ThemeMenu() {
	const preference = useSyncExternalStore(theme.subscribe, theme.get),
		[open, setOpen] = useState(false);
	const area = useRef<HTMLDivElement>(null),
		trigger = useRef<HTMLButtonElement>(null),
		menu = useRef<HTMLDivElement>(null);
	useEffect(() => {
		const close = (e: PointerEvent) => {
			if (!area.current?.contains(e.target as Node)) setOpen(false);
		};
		document.addEventListener('pointerdown', close);
		return () => document.removeEventListener('pointerdown', close);
	}, []);
	useEffect(() => {
		if (open) menu.current?.querySelector<HTMLButtonElement>('[aria-checked=true]')?.focus();
	}, [open]);
	return (
		<div className="theme-area" ref={area}>
			<button
				ref={trigger}
				id="theme-trigger"
				className="icon-button"
				aria-label={'Theme: ' + preference}
				title={'Theme: ' + preference}
				aria-haspopup="menu"
				aria-expanded={open}
				onClick={() => setOpen(!open)}
			>
				<Icon name={preference} />
			</button>
			<div
				id="theme-menu"
				ref={menu}
				role="menu"
				hidden={!open}
				onKeyDown={(e) => {
					if (e.key === 'Escape') {
						setOpen(false);
						trigger.current?.focus();
					}
					if (['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp'].includes(e.key)) {
						e.preventDefault();
						const buttons = [...menu.current!.querySelectorAll('button')];
						const i = buttons.indexOf(document.activeElement as HTMLButtonElement);
						buttons[(i + (['ArrowRight', 'ArrowDown'].includes(e.key) ? 1 : 2)) % 3]?.focus();
					}
				}}
			>
				{(['Auto', 'Light', 'Dark'] as Preference[]).map((name) => (
					<button
						key={name}
						className="icon-button"
						role="menuitemradio"
						aria-checked={name === preference}
						aria-label={name}
						title={name}
						onClick={() => {
							theme.set(name);
							setOpen(false);
							trigger.current?.focus();
						}}
					>
						<Icon name={name} />
					</button>
				))}
			</div>
		</div>
	);
}
