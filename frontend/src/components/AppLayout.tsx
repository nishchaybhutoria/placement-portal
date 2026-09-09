import {
  Bell,
  Briefcase,
  Building2,
  CalendarRange,
  FileText,
  Mail,
  LayoutGrid,
  ListChecks,
  Menu,
  Monitor,
  Moon,
  SearchCheck,
  Settings,
  Sun,
  ShieldAlert,
  ChartNoAxesCombined,
  Upload,
  Users,
  ShieldCheck,
  Tags,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import type { Me } from "@/api/client";
import { command } from "@/api/client";
import { cn } from "@/lib/cn";
import { getTheme, setTheme, watchSystem, THEMES, type Theme } from "@/lib/theme";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./ui/dialog";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /**
   * Visibility only. The server authorises every screen and command
   * independently — hiding a link never grants or withholds access.
   */
  visible: (me: Me) => boolean;
}

const isAdmin = (me: Me) => me.user?.role === "admin";
const isStudent = (me: Me) => !isAdmin(me);
const isStaff = (me: Me) => isAdmin(me) || (me.coordinated_cycle_ids?.length ?? 0) > 0;

const NAV: NavItem[] = [
  { to: "/", label: "Home", icon: LayoutGrid, visible: () => true },
  { to: "/dashboard", label: "Dashboard", icon: Briefcase, visible: isStudent },
  { to: "/profile", label: "My profile", icon: UserRound, visible: isStudent },
  { to: "/cycles", label: "Cycles", icon: CalendarRange, visible: isStudent },
  { to: "/applications", label: "My applications", icon: FileText, visible: isStudent },
  { to: "/notifications", label: "Notifications", icon: Mail, visible: isStudent },
  { to: "/staff/cycles", label: "Manage cycles", icon: ListChecks, visible: isStaff },
  { to: "/staff/companies", label: "Companies", icon: Building2, visible: isStaff },
  { to: "/staff/external", label: "External offers", icon: Briefcase, visible: isStaff },
  { to: "/admin/users", label: "Users", icon: Users, visible: isAdmin },
  { to: "/admin/bulk-upsert", label: "Bulk upsert", icon: Upload, visible: isAdmin },
  { to: "/admin/analytics", label: "Portal analytics", icon: ChartNoAxesCombined, visible: isAdmin },
  { to: "/admin/discipline", label: "Discipline", icon: ShieldAlert, visible: isAdmin },
  { to: "/admin/taxonomies", label: "Taxonomies", icon: Tags, visible: isAdmin },
  { to: "/admin/settings", label: "Settings", icon: Settings, visible: isAdmin },
  // INT-2 grants create_override to staff of the cycle, so the register that
  // shows what they granted is theirs to read; the screen scopes a coordinator
  // to their own cycles.
  { to: "/admin/overrides", label: "Overrides", icon: ShieldCheck, visible: isStaff },
  { to: "/admin/findings", label: "Findings", icon: SearchCheck, visible: isAdmin },
  { to: "/admin/templates", label: "Notifications", icon: Bell, visible: isAdmin },
];

export function AppLayout({ me }: { me: Me }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-background">
      {/*
        WCAG 2.4.1. The primary nav is up to thirteen links and it precedes the
        page on every route, so without this a keyboard user tabs the whole rail
        before reaching anything they came for. `sr-only` until focused, and
        first in the DOM so it is the first stop.
      */}
      <a
        href="#main-content"
        className={cn(
          "sr-only focus:not-sr-only",
          "focus:fixed focus:left-gap-lg focus:top-gap-lg focus:z-50",
          "focus:rounded focus:border focus:border-border focus:bg-card",
          "focus:px-gap-lg focus:py-gap-md focus:text-body-md focus:text-foreground",
          "focus:outline-hidden focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background",
        )}
      >
        Skip to content
      </a>
      {/*
        `sticky top-0 h-screen` is what makes the rail a rail. Without a height
        of its own it inherits the flex row's stretch, which is the height of
        the *page*: on a long board the theme control and Sign out sit at the
        bottom of a three-thousand-pixel column, and Navigation's `flex-1
        overflow-y-auto` never engages because there is no bound to overflow.
      */}
      <aside className="sticky top-0 hidden h-screen w-sidebar shrink-0 flex-col border-r border-border bg-card lg:flex">
        <div className="flex h-14 items-center border-b border-border px-gap-lg">
          <span className="text-headline-md text-foreground">CDS Portal</span>
        </div>
        <Navigation me={me} />
        <Account me={me} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-border bg-card px-gap-lg lg:hidden">
          <span className="text-headline-md text-foreground">CDS Portal</span>
          <Dialog open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
            <DialogTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Open navigation">
                <Menu aria-hidden className="h-5 w-5" />
              </Button>
            </DialogTrigger>
            <DialogContent className="max-h-[calc(100vh-2rem)] max-w-[calc(100%-2rem)]">
              <DialogHeader>
                <DialogTitle>Navigation</DialogTitle>
                <DialogDescription>Pages available to your account.</DialogDescription>
              </DialogHeader>
              <Navigation me={me} onNavigate={() => setMobileNavOpen(false)} />
              <Account me={me} />
            </DialogContent>
          </Dialog>
        </header>

        {/* tabIndex -1 so the skip link moves focus here, not just the viewport. */}
        <main id="main-content" tabIndex={-1} className="min-w-0 flex-1 focus:outline-hidden">
          <div className="mx-auto flex max-w-6xl flex-col gap-section-margin p-gap-lg sm:p-container-padding">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

function Navigation({ me, onNavigate }: { me: Me; onNavigate?: () => void }) {
  return (
    <nav aria-label="Primary" className="flex flex-1 flex-col gap-gap-tight overflow-y-auto p-gap-md">
      {NAV.filter((item) => item.visible(me)).map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-gap-md rounded px-gap-md py-gap-md text-body-md transition-colors",
              "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              isActive
                ? "bg-brand-subtle font-semibold text-brand"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )
          }
        >
          <item.icon aria-hidden className="h-4 w-4" />
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

const THEME_ICON: Record<Theme, LucideIcon> = {
  system: Monitor,
  light: Sun,
  dark: Moon,
};

const THEME_LABEL: Record<Theme, string> = {
  system: "Match system",
  light: "Light",
  dark: "Dark",
};

/**
 * System / Light / Dark, as a segmented control rather than a two-way switch.
 *
 * "Match system" has to be reachable as its own state: a plain toggle can only
 * record a side, so a viewer who wants the portal to follow their machine has
 * no way to say so once they have touched it.
 */
function ThemeControl() {
  const [theme, setThemeState] = useState<Theme>(getTheme);
  useEffect(watchSystem, []);
  return (
    <div role="group" aria-label="Theme" className="flex gap-gap-tight">
      {THEMES.map((option) => {
        const Icon = THEME_ICON[option];
        const active = theme === option;
        return (
          <button
            key={option}
            type="button"
            aria-label={THEME_LABEL[option]}
            aria-pressed={active}
            title={THEME_LABEL[option]}
            onClick={() => {
              setTheme(option);
              setThemeState(option);
            }}
            className={cn(
              "flex h-7 flex-1 items-center justify-center rounded border transition-colors",
              "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              active
                ? "border-brand-border bg-brand-subtle text-brand"
                : "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon aria-hidden className="h-4 w-4" />
          </button>
        );
      })}
    </div>
  );
}

function Account({ me }: { me: Me }) {
  return (
    <div className="flex flex-col gap-gap-md border-t border-border p-gap-lg">
      <div className="min-w-0">
        <p className="truncate text-body-md font-medium text-foreground">
          {me.user?.full_name ?? me.user?.email ?? "Signed in"}
        </p>
        <p className="truncate text-body-sm capitalize text-muted-foreground">
          {me.user?.role ?? ""}
        </p>
      </div>
      <ThemeControl />
      <Button
        variant="ghost"
        size="sm"
        className="justify-start"
        onClick={() => {
          void command("logout", {} as never).finally(() => window.location.assign("/"));
        }}
      >
        Sign out
      </Button>
    </div>
  );
}
