import { useEffect } from 'react';
import { createRootRoute, Link, Outlet, useLocation, useMatchRoute } from '@tanstack/react-router';
import {
	BookOpen,
	Camera,
	Crosshair,
	GitCompareArrows,
	Network as NetworkIcon,
	Server,
	TriangleAlert,
} from 'lucide-react';
import { useDashboard, useServiceError } from '../dashboard';
import { loadStatus, useStatus } from '../queries';
import { date } from '../components/common';
import { ThemeMenu } from '../components/ThemeMenu';
import { count } from '../state/changes';
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarGroup,
	SidebarHeader,
	SidebarInset,
	SidebarMenu,
	SidebarMenuBadge,
	SidebarMenuButton,
	SidebarMenuItem,
	SidebarMenuSub,
	SidebarMenuSubButton,
	SidebarMenuSubItem,
	SidebarProvider,
	SidebarTrigger,
	useSidebar,
} from '@/components/ui/sidebar';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { TooltipProvider } from '@/components/ui/tooltip';
/** Close the mobile navigation sheet after following one of its links. */
function CloseMobileSidebar() {
	const { setOpenMobile } = useSidebar(),
		pathname = useLocation({ select: (location) => location.pathname });
	useEffect(() => setOpenMobile(false), [pathname, setOpenMobile]);
	return null;
}
export const Route = createRootRoute({ loader: loadStatus, component: Root });
const top = [{ to: '/', label: 'Cameras', icon: Camera }] as const;
const bottom = [
	{ to: '/calibration', label: 'Calibration', icon: Crosshair },
	{ to: '/changes', label: 'Changes', icon: GitCompareArrows },
	{ to: '/network', label: 'Network', icon: NetworkIcon },
	{ to: '/system', label: 'System', icon: Server },
] as const;
function Root() {
	const { message } = useDashboard(),
		status = useStatus(),
		serviceError = useServiceError(),
		matchRoute = useMatchRoute(),
		// The docs pane fills the content area and has its own layout.
		docs = Boolean(matchRoute({ to: '/help/$' }));
	const link = (item: (typeof top | typeof bottom)[number]) => (
		<SidebarMenuItem key={item.to}>
			<SidebarMenuButton
				// Calibration owns its tabs; the camera pages have their own sidebar entries.
				isActive={Boolean(matchRoute({ to: item.to, fuzzy: item.to === '/calibration' }))}
				tooltip={item.label}
				render={<Link to={item.to} />}
			>
				<item.icon />
				<span>{item.label}</span>
			</SidebarMenuButton>
			{item.to === '/changes' && status.overrides?.length ? (
				<SidebarMenuBadge aria-label={`${count(status.overrides.length, 'change', 'changes')} not in robot code`}>
					{status.overrides.length}
				</SidebarMenuBadge>
			) : null}
		</SidebarMenuItem>
	);
	return (
		<TooltipProvider>
			<SidebarProvider defaultOpen={matchMedia('(min-width: 1150px)').matches}>
				<CloseMobileSidebar />
				<a
					className="fixed -top-24 left-4 z-50 rounded-md bg-background p-2 shadow focus:top-2"
					href="#main"
					onClick={(e) => {
						e.preventDefault();
						document.getElementById('main')?.focus();
					}}
				>
					Skip to content
				</a>
				<Sidebar collapsible="icon" aria-label="Main navigation">
					<SidebarHeader>
						<SidebarMenu>
							<SidebarMenuItem>
								<SidebarMenuButton size="lg" render={<Link to="/" />}>
									<img src="/blazing-bulldogs.svg" alt="Blazing Bulldogs" className="size-8 object-contain" />
									<span className="font-heading text-xl font-semibold">Spot</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
						</SidebarMenu>
					</SidebarHeader>
					<SidebarContent>
						<SidebarGroup>
							<SidebarMenu>
								{top.map(link)}
								{status.cameras.length ? (
									<SidebarMenuSub>
										{status.cameras.map((c) => {
											const warnings = [];
											if (c.health !== 'Disabled' && !c.logical_name) warnings.push('Choose a code-defined name');
											if (c.health !== 'Disabled' && c.logical_name && !c.calibrated)
												warnings.push('Calibration required');
											if (c.health !== 'Disabled' && !c.connected)
												warnings.push(c.present ? c.fault || 'Waiting for image' : 'Disconnected');
											return (
												<SidebarMenuSubItem key={c.identity}>
													<SidebarMenuSubButton
														isActive={Boolean(
															matchRoute({ to: '/cameras/$id', params: { id: c.identity }, fuzzy: true }),
														)}
														aria-label={c.name + (warnings.length ? ': ' + warnings.join('; ') : '')}
														render={<Link to="/cameras/$id" params={{ id: c.identity }} />}
													>
														<span>{c.name}</span>
														{warnings.length ? <TriangleAlert className="ml-auto text-warning!" aria-hidden /> : null}
													</SidebarMenuSubButton>
												</SidebarMenuSubItem>
											);
										})}
									</SidebarMenuSub>
								) : null}
							</SidebarMenu>
						</SidebarGroup>
						<SidebarGroup>
							<SidebarMenu>
								{bottom.map(link)}
								<SidebarMenuItem>
									<SidebarMenuButton
										isActive={Boolean(matchRoute({ to: '/help/$' }))}
										tooltip="Docs"
										render={<Link to="/help/$" params={{ _splat: '' }} />}
									>
										<BookOpen />
										<span>Docs</span>
									</SidebarMenuButton>
								</SidebarMenuItem>
							</SidebarMenu>
						</SidebarGroup>
					</SidebarContent>
					<SidebarFooter>
						<ThemeMenu />
						<SidebarTrigger className="max-md:hidden" />
						<div className="px-2 text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
							<div>
								{status.software.process_started_at
									? 'Started ' + date(status.software.process_started_at)
									: 'Time unavailable'}
							</div>
							<small title={status.software.package_path}>
								{status.software.version ? 'Spot ' + status.software.version : 'Development'}
							</small>
						</div>
					</SidebarFooter>
				</Sidebar>
				<SidebarInset id="main" tabIndex={-1} className="min-w-0 outline-none">
					<header className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background/90 px-4 py-2 backdrop-blur md:hidden">
						<SidebarTrigger />
						<span className="font-heading font-semibold">Spot</span>
					</header>
					{docs ? (
						<Outlet />
					) : (
						<div className="flex flex-col gap-5 p-4 md:p-6 lg:p-8">
							{status.overrides?.length ? (
								<Alert role="status">
									<TriangleAlert />
									<AlertDescription>
										<span>
											{count(status.overrides.length, 'setting on Spot differs', 'settings on Spot differ')} from robot
											code. <Link to="/changes">Review changes</Link>
										</span>
									</AlertDescription>
								</Alert>
							) : null}
							<Outlet />
						</div>
					)}
				</SidebarInset>
				<div id="announcement" className="sr-only" role="status" aria-live="polite">
					{serviceError || message}
				</div>
			</SidebarProvider>
		</TooltipProvider>
	);
}
