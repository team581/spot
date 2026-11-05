import { useSyncExternalStore } from 'react';
import { Monitor, Moon, Sun } from 'lucide-react';
import { theme } from '../theme';
import type { Preference } from '../state/theme';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuRadioGroup,
	DropdownMenuRadioItem,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { SidebarMenuButton } from '@/components/ui/sidebar';
const icons = { Auto: Monitor, Light: Sun, Dark: Moon };
export function ThemeMenu() {
	const preference = useSyncExternalStore(theme.subscribe, theme.get),
		Icon = icons[preference];
	return (
		<DropdownMenu>
			<DropdownMenuTrigger
				render={<SidebarMenuButton aria-label={'Theme: ' + preference} tooltip={'Theme: ' + preference} />}
			>
				<Icon />
				<span>Theme: {preference}</span>
			</DropdownMenuTrigger>
			<DropdownMenuContent side="top" align="start">
				<DropdownMenuRadioGroup value={preference} onValueChange={(value) => theme.set(value as Preference)}>
					{(['Auto', 'Light', 'Dark'] as const).map((name) => {
						const ItemIcon = icons[name];
						return (
							<DropdownMenuRadioItem key={name} value={name}>
								<ItemIcon />
								{name}
							</DropdownMenuRadioItem>
						);
					})}
				</DropdownMenuRadioGroup>
			</DropdownMenuContent>
		</DropdownMenu>
	);
}
