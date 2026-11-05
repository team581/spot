import { lazy, Suspense, useEffect, useState } from 'react';
import {
	BookOpen,
	Camera,
	Crosshair,
	LayoutDashboard,
	Network as NetworkIcon,
	Server,
	TriangleAlert,
} from 'lucide-react';
import { useDashboard, useServiceError } from './dashboard';
import { useStatus } from './queries';
import { date } from './components/common';
import { ThemeMenu } from './components/ThemeMenu';
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
import { Alert, AlertDescription } from '@/components/ui/alert';
import { TooltipProvider } from '@/components/ui/tooltip';
import Overview from './pages/Overview';
const CameraName = lazy(() => import('./pages/CameraName'));
const CameraDetail = lazy(() => import('./pages/CameraDetail'));
const Geometry = lazy(() => import('./pages/Geometry'));
const Calibration = lazy(() => import('./pages/Calibration'));
const Network = lazy(() => import('./pages/Network'));
const System = lazy(() => import('./pages/System'));
function route() {
	const parts = location.hash
		.slice(1)
		.split('/')
		.map((part) => {
			try {
				return decodeURIComponent(part);
			} catch {
				return part;
			}
		});
	return { page: parts[0] || 'overview', id: parts[1], tab: parts[2] };
}
/** Close the mobile navigation sheet after following one of its links. */
function CloseMobileSidebar({ route }: { route: object }) {
	const { setOpenMobile } = useSidebar();
	useEffect(() => setOpenMobile(false), [route, setOpenMobile]);
	return null;
}
const top = [
	{ page: 'overview', label: 'Overview', icon: LayoutDashboard },
	{ page: 'cameras', label: 'Cameras', icon: Camera },
];
const bottom = [
	{ page: 'calibration', label: 'Calibration', icon: Crosshair },
	{ page: 'network', label: 'Network', icon: NetworkIcon },
	{ page: 'system', label: 'System', icon: Server },
];
export default function App() {
	const { message } = useDashboard(),
		status = useStatus(),
		serviceError = useServiceError(),
		[current, setCurrent] = useState(route);
	useEffect(() => {
		const changed = () => setCurrent(route());
		addEventListener('hashchange', changed);
		return () => removeEventListener('hashchange', changed);
	}, []);
	const camera = status.cameras.find((c) => c.identity === current.id);
	const page =
		current.page === 'overview' || current.page === 'cameras' ? (
			<Overview page={current.page} />
		) : current.page === 'camera' && camera ? (
			!camera.logical_name && !camera.standalone_setup ? (
				<CameraName key={camera.identity} camera={camera} />
			) : current.tab === 'geometry' ? (
				<Geometry key={camera.identity} camera={camera} />
			) : (
				<CameraDetail
					key={camera.identity + '/' + Boolean(camera.logical_name) + '/' + Boolean(camera.standalone_setup)}
					camera={camera}
				/>
			)
		) : current.page === 'calibration' ? (
			<Calibration results={current.id === 'results'} />
		) : current.page === 'network' ? (
			<Network />
		) : current.page === 'system' ? (
			<System />
		) : (
			<>
				<h1 className="font-heading text-2xl font-semibold">Camera unavailable</h1>
				<p>
					The configured camera may be disconnected. <a href="#cameras">Open Cameras</a>
				</p>
			</>
		);
	const link = (item: (typeof top)[number]) => (
		<SidebarMenuItem key={item.page}>
			<SidebarMenuButton
				isActive={current.page === item.page}
				tooltip={item.label}
				render={<a href={'#' + item.page} />}
			>
				<item.icon />
				<span>{item.label}</span>
			</SidebarMenuButton>
		</SidebarMenuItem>
	);
	return (
		<TooltipProvider>
			<SidebarProvider defaultOpen={matchMedia('(min-width: 1150px)').matches}>
				<CloseMobileSidebar route={current} />
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
								<SidebarMenuButton size="lg" render={<a href="#overview" />}>
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
														isActive={current.page === 'camera' && current.id === c.identity}
														aria-label={c.name + (warnings.length ? ': ' + warnings.join('; ') : '')}
														render={<a href={'#camera/' + encodeURIComponent(c.identity)} />}
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
									<SidebarMenuButton tooltip="Docs" render={<a href="/docs/" />}>
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
					<div className="flex flex-col gap-5 p-4 md:p-6 lg:p-8">
						{status.has_overrides ? (
							<Alert role="status">
								<TriangleAlert />
								<AlertDescription>
									<span>
										Saved dashboard overrides are active. <a href="#system">Manage overrides</a> or export the effective
										configuration.
									</span>
								</AlertDescription>
							</Alert>
						) : null}
						<Suspense fallback={<p>Loading…</p>}>{page}</Suspense>
					</div>
				</SidebarInset>
				<div id="announcement" className="sr-only" role="status" aria-live="polite">
					{serviceError || message}
				</div>
			</SidebarProvider>
		</TooltipProvider>
	);
}
