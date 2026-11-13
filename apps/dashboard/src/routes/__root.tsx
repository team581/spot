import { useEffect } from 'react';
import { createRootRoute, Link, Outlet, useLocation, useMatchRoute } from '@tanstack/react-router';
import {
	BookOpen,
	Camera,
	Crosshair,
	FileCog,
	HardDrive,
	Network as NetworkIcon,
	Server,
	TriangleAlert,
} from 'lucide-react';
import { useStatus } from '../queries';
import { stateLabel } from '../components/common';
import { ThemeMenu } from '../components/ThemeMenu';
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarGroup,
	SidebarHeader,
	SidebarInset,
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
	SidebarMenuSub,
	SidebarMenuSubButton,
	SidebarMenuSubItem,
	SidebarProvider,
	SidebarTrigger,
	useSidebar,
} from '@/components/ui/sidebar';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { TooltipProvider } from '@/components/ui/tooltip';
/** Close the mobile navigation sheet after following one of its links. */
function CloseMobileSidebar() {
	const { setOpenMobile } = useSidebar(),
		pathname = useLocation({ select: (location) => location.pathname });
	useEffect(() => setOpenMobile(false), [pathname, setOpenMobile]);
	return null;
}
export const Route = createRootRoute({ component: Root });
const pages = [
	{ to: '/calibration', label: 'Calibration', icon: Crosshair },
	{ to: '/config', label: 'Config', icon: FileCog },
	{ to: '/network', label: 'Network', icon: NetworkIcon },
	{ to: '/system', label: 'System', icon: Server },
	// `/recordings/` serves the recording files themselves.
	{ to: '/downloads', label: 'Recordings', icon: HardDrive },
] as const;
function Root() {
	const { data: status, isError } = useStatus(),
		matchRoute = useMatchRoute(),
		// The docs pane fills the content area and has its own layout.
		docs = Boolean(matchRoute({ to: '/help/$' }));
	return (
		<TooltipProvider>
			<SidebarProvider defaultOpen={matchMedia('(min-width: 1150px)').matches}>
				<CloseMobileSidebar />
				<Sidebar collapsible="icon">
					<SidebarHeader>
						<SidebarMenu>
							<SidebarMenuItem>
								<SidebarMenuButton size="lg" render={<Link to="/" />}>
									<img src="/logo.svg" alt="" className="size-8 object-contain" />
									<span className="font-heading text-xl font-semibold">Spot</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
						</SidebarMenu>
					</SidebarHeader>
					<SidebarContent>
						<SidebarGroup>
							<SidebarMenu>
								<SidebarMenuItem>
									<SidebarMenuButton
										isActive={Boolean(matchRoute({ to: '/' }) || matchRoute({ to: '/devices' }))}
										tooltip="Cameras"
										render={<Link to="/" />}
									>
										<Camera />
										<span>Cameras</span>
									</SidebarMenuButton>
									{status?.cameras.length ? (
										<SidebarMenuSub>
											{status.cameras.map((c) => (
												<SidebarMenuSubItem key={c.name}>
													<SidebarMenuSubButton
														isActive={Boolean(matchRoute({ to: '/cameras/$name', params: { name: c.name } }))}
														render={<Link to="/cameras/$name" params={{ name: c.name }} />}
													>
														<span>{c.name}</span>
														{c.state === 'streaming' ? null : <TriangleAlert className="ml-auto text-warning!" />}
													</SidebarMenuSubButton>
												</SidebarMenuSubItem>
											))}
										</SidebarMenuSub>
									) : null}
								</SidebarMenuItem>
								{pages.map((item) => (
									<SidebarMenuItem key={item.to}>
										<SidebarMenuButton
											isActive={Boolean(matchRoute({ to: item.to, fuzzy: true }))}
											tooltip={item.label}
											render={<Link to={item.to} />}
										>
											<item.icon />
											<span>{item.label}</span>
										</SidebarMenuButton>
									</SidebarMenuItem>
								))}
								<SidebarMenuItem>
									<SidebarMenuButton
										isActive={docs}
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
						<small className="px-2 text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
							{status ? 'Spot ' + status.version : 'Spot'}
						</small>
					</SidebarFooter>
				</Sidebar>
				<SidebarInset className="min-w-0">
					<header className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background/90 px-4 py-2 backdrop-blur md:hidden">
						<SidebarTrigger />
						<span className="font-heading font-semibold">Spot</span>
					</header>
					{docs ? (
						<Outlet />
					) : (
						<div className="flex flex-col gap-5 p-4 md:p-6 lg:p-8">
							{isError ? (
								<Alert variant="destructive">
									<TriangleAlert />
									<AlertTitle>Spot is not responding</AlertTitle>
									<AlertDescription>Reconnecting…</AlertDescription>
								</Alert>
							) : status && status.state !== 'ready' ? (
								<Alert>
									<TriangleAlert className="text-warning!" />
									<AlertTitle>{stateLabel(status.state)}</AlertTitle>
									{status.error ? <AlertDescription>{status.error}</AlertDescription> : null}
								</Alert>
							) : null}
							{status?.overrides_active ? (
								<Alert>
									<FileCog />
									<AlertDescription>
										<span>
											Dashboard overrides differ from the robot config. <Link to="/config">Review overrides</Link>
										</span>
									</AlertDescription>
								</Alert>
							) : null}
							<Outlet />
						</div>
					)}
				</SidebarInset>
			</SidebarProvider>
		</TooltipProvider>
	);
}
