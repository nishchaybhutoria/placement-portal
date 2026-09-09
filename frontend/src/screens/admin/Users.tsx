import { useState } from "react";

import { payload, type AdminUsersPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select } from "@/components/ui/input";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { formatDate } from "@/lib/date";
import { counted, humanise } from "@/lib/text";
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from "@/lib/useDebouncedValue";

export function Users() {
  const [query, setQuery] = useState("");
  const [includeInactive, setIncludeInactive] = useState(true);
  const search = useDebouncedValue(query.trim(), SEARCH_DEBOUNCE_MS);
  const screen = useScreen("admin/users", {
    query: { q: search || undefined, include_inactive: includeInactive },
    keepPrevious: true,
  });

  if (screen.isPending) return <ScreenSkeleton variant="cards" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }
  const data = payload<AdminUsersPayload>(screen.data);
  return (
    <>
      <PageHeader
        title="Users and enrollments"
        subtitle={`${data.counts.active} active of ${data.counts.total} shown · ${counted(data.counts.admins, "administrator")}`}
      />
      <Card>
        <CardHeader><CardTitle>Directory</CardTitle></CardHeader>
        <CardBody className="flex flex-wrap items-end gap-gap-lg">
          <Field label="Search" className="min-w-64 flex-1">
            {(field) => <Input {...field} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Name, email, or roll" />}
          </Field>
          <label className="flex h-control items-center gap-gap-md text-body-md text-foreground">
            <Checkbox checked={includeInactive} onChange={(event) => setIncludeInactive(event.target.checked)} />
            Include inactive
          </label>
        </CardBody>
      </Card>
      {data.users.length === 0 ? (
        <EmptyState message="No user matches these filters." />
      ) : (
        <div className="flex flex-col gap-gap-lg">
          {data.users.map((user) => <UserCard key={user.id} user={user} />)}
        </div>
      )}
    </>
  );
}

function UserCard({ user }: { user: AdminUsersPayload["users"][number] }) {
  const [role, setRole] = useState(user.role);
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{user.full_name}</CardTitle>
          <p className="mt-gap-tight text-body-sm text-muted-foreground">{user.email} · {user.is_active ? "Active" : "Inactive"}</p>
        </div>
        <span className="text-body-sm text-muted-foreground">{humanise(user.role)}</span>
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        <div className="grid gap-gap-lg sm:grid-cols-3">
          <Fact label="Current roll" value={user.current_enrollment?.roll_number ?? "—"} />
          <Fact label="Profile" value={user.current_enrollment?.profile_declared ? "Declared" : "Not declared"} />
          <Fact label="Enrollments" value={String(user.enrollment_count)} />
        </div>
        <div className="flex flex-wrap items-end gap-gap-md">
          <Field label="Role">
            {(field) => (
              <Select {...field} value={role} disabled={!user.actions.set_role.allowed} onChange={(event) => setRole(event.target.value as "student" | "admin")}>
                <option value="student">Student</option>
                <option value="admin">Administrator</option>
              </Select>
            )}
          </Field>
          <PreviewConfirm
            command="set_user_role"
            input={{ user_id: user.id, role }}
            title={`Change ${user.full_name}'s role to ${role}?`}
            confirmLabel="Change role"
            destructive={role === "student" && user.role === "admin"}
            trigger={<Button variant="secondary" disabled={role === user.role || !user.actions.set_role.allowed} title={user.actions.set_role.human ?? undefined}>Change role</Button>}
          />
          <PreviewConfirm
            command="start_new_enrollment"
            input={{ user_id: user.id }}
            title={`Start a new enrollment for ${user.full_name}?`}
            description="The current enrollment becomes historical. Placement, applications, offers, and discipline remain attached to it; the new enrollment starts empty."
            confirmLabel="Start new enrollment"
            trigger={<Button variant="secondary" disabled={!user.actions.start_new_enrollment.allowed} title={user.actions.start_new_enrollment.human ?? undefined}>Start new enrollment</Button>}
          />
          <PreviewConfirm
            command="deactivate_user"
            input={{ user_id: user.id }}
            title={`Deactivate ${user.full_name}?`}
            description="Every active session is revoked immediately."
            confirmLabel="Deactivate user"
            destructive
            trigger={<Button variant="destructive-ghost" disabled={!user.actions.deactivate.allowed} title={user.actions.deactivate.human ?? undefined}>Deactivate</Button>}
          />
        </div>
        <details className="text-body-sm">
          <summary className="cursor-pointer text-muted-foreground">Enrollment history ({user.enrollments.length})</summary>
          {user.enrollments.length === 0 ? (
            <p className="mt-gap-md text-muted-foreground">No enrollment history.</p>
          ) : (
            <ul className="mt-gap-md flex flex-col gap-gap-tight border-l border-border pl-gap-lg">
              {user.enrollments.map((enrollment) => (
                <li key={enrollment.id} className="text-foreground">
                  {enrollment.roll_number ?? "No roll"} · {formatDate(enrollment.created_at)}{enrollment.is_current ? " · Current" : ""}
                </li>
              ))}
            </ul>
          )}
        </details>
      </CardBody>
    </Card>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><p className="text-body-sm text-muted-foreground">{label}</p><p className="text-body-md text-foreground">{value}</p></div>;
}
