import { ArrowLeft, Plus } from "lucide-react";
import { Suspense, lazy, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  payload,
  type CompaniesPayload,
  type CompanyPayload,
} from "@/api/payloads";
import { useCommand, useScreen } from "@/api/useScreen";

import { PageHeader } from "@/components/PageHeader";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select, Textarea } from "@/components/ui/input";
import { DataTable, type Column } from "@/components/ui/table";
import { EmptyState, ErrorState, ScreenSkeleton, Skeleton } from "@/components/ui/states";
import { humanise } from "@/lib/text";

type Contact = CompanyPayload["contacts"][number];

/** Charts are deferred here for the same reason they are in App.tsx. */
const CompanyAnalyticsPanel = lazy(() =>
  import("@/screens/analytics/CompanyAnalyticsPanel").then((m) => ({
    default: m.CompanyAnalyticsPanel,
  })),
);

export function Company() {
  const { id = "" } = useParams();
  const screen = useScreen("staff/company/{id}", { params: { id } });
  const directory = useScreen("staff/companies", { query: { include_inactive: true } });
  const [addingContact, setAddingContact] = useState(false);
  const [editingCompany, setEditingCompany] = useState(false);

  if (screen.isPending || directory.isPending) {
    return <ScreenSkeleton variant="detail" />;
  }
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }
  if (directory.isError) {
    return <ErrorState error={directory.error} onRetry={() => void directory.refetch()} />;
  }

  const data = payload<CompanyPayload>(screen.data);
  const others = directory.data
    ? payload<CompaniesPayload>(directory.data).companies.filter(
        (company) => company.id !== id,
      )
    : [];

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link
            to="/staff/companies"
            className="inline-flex items-center gap-gap-tight hover:underline"
          >
            <ArrowLeft className="h-3 w-3" /> Companies
          </Link>
        }
        title={data.company.name}
        subtitle={data.company.description ?? undefined}
        actions={
          <>
            <Button variant="secondary" onClick={() => setEditingCompany((open) => !open)}>
              Edit details
            </Button>
            {data.actions.manage_activity.allowed && data.company.is_active ? (
              <PreviewConfirm
                command="deactivate_company"
                input={{ company_id: id }}
                title={`Deactivate ${data.company.name}?`}
                description="It disappears from every picker. An administrator can reactivate it."
                confirmLabel="Deactivate"
                destructive
                trigger={<Button variant="destructive-ghost">Deactivate</Button>}
              />
            ) : data.actions.manage_activity.allowed ? (
              <PreviewConfirm
                command="activate_company"
                input={{ company_id: id }}
                title={`Reactivate ${data.company.name}?`}
                confirmLabel="Reactivate"
                trigger={<Button variant="secondary">Reactivate</Button>}
              />
            ) : null}
            <MergeAction
              company={data.company}
              others={others}
              permission={data.actions.merge}
            />
          </>
        }
      />

      {editingCompany ? (
        <EditCompany
          company={data.company}
          sectors={directory.data ? payload<CompaniesPayload>(directory.data).sectors : []}
          onDone={() => setEditingCompany(false)}
        />
      ) : null}

      {!data.company.is_active ? (
        <div className="rounded border border-warning-border bg-warning-subtle p-container-padding">
          <p className="text-body-md font-semibold text-warning">This company is inactive</p>
          <p className="mt-gap-tight text-body-md text-foreground">
            It is hidden from every picker, so no new job can name it until an administrator
            reactivates it.
          </p>
        </div>
      ) : null}

      <div className="grid gap-section-margin lg:grid-cols-[2fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Contacts</CardTitle>
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus className="h-4 w-4" />}
              onClick={() => setAddingContact((open) => !open)}
            >
              Add contact
            </Button>
          </CardHeader>
          {addingContact ? (
            <CardBody className="border-b border-border">
              <AddContact companyId={id} onDone={() => setAddingContact(false)} />
            </CardBody>
          ) : null}
          <ContactTable companyId={id} contacts={data.contacts} />
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <CardBody>
            <dl className="flex flex-col gap-gap-lg text-body-md">
              <Fact label="Sector" value={data.company.sector?.name ?? "—"} />
              <Fact
                label="Website"
                value={
                  data.company.website_url ? (
                    <a
                      href={data.company.website_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-accent hover:underline"
                    >
                      {data.company.website_url}
                    </a>
                  ) : (
                    "—"
                  )
                }
              />
              <Fact label="Jobs" value={String(data.jobs.length)} />
              <Fact label="External offers" value={String(data.external_offer_count)} />
            </dl>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Jobs</CardTitle>
        </CardHeader>
        <DataTable
          columns={[
            {
              key: "title",
              header: "Job",
              cell: (job: CompanyPayload["jobs"][number]) => (
                <Link
                  to={`/staff/jobs/${job.id}?cycle_id=${job.cycle.id}`}
                  className="font-medium text-accent hover:underline"
                >
                  {job.title}
                </Link>
              ),
            },
            {
              key: "cycle",
              header: "Cycle",
              cell: (job: CompanyPayload["jobs"][number]) => job.cycle.name,
            },
            {
              key: "outcome",
              header: "Outcome",
              cell: (job: CompanyPayload["jobs"][number]) => (
                <span>{humanise(job.outcome)}</span>
              ),
            },
            {
              key: "state",
              header: "State",
              cell: (job: CompanyPayload["jobs"][number]) =>
                job.is_cancelled ? (
                  <span className="text-danger">Cancelled</span>
                ) : job.is_published ? (
                  "Published"
                ) : (
                  <span className="text-muted-foreground">Draft</span>
                ),
            },
          ]}
          rows={data.jobs}
          rowKey={(job) => job.id}
          empty={
            <CardBody>
              <EmptyState message="No job has named this company yet." />
            </CardBody>
          }
        />
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Across cycles</CardTitle>
        </CardHeader>
        <CardBody>
          <Suspense fallback={<Skeleton className="h-64 w-full" />}>
            <CompanyAnalyticsPanel analytics={data.analytics} />
          </Suspense>
        </CardBody>
      </Card>
    </>
  );
}

function EditCompany({
  company,
  sectors,
  onDone,
}: {
  company: CompanyPayload["company"];
  sectors: CompaniesPayload["sectors"];
  onDone: () => void;
}) {
  const update = useCommand("update_company");
  const [name, setName] = useState(company.name);
  const [description, setDescription] = useState(company.description ?? "");
  const [website, setWebsite] = useState(company.website_url ?? "");
  const [sectorId, setSectorId] = useState(company.sector?.id ?? "");
  return (
    <Card>
      <CardHeader><CardTitle>Edit company</CardTitle></CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        {update.isError ? <ErrorState error={update.error} title="Could not update company" /> : null}
        <div className="grid gap-gap-lg sm:grid-cols-2">
          <Field label="Name" required>
            {(field) => <Input {...field} value={name} onChange={(event) => setName(event.target.value)} />}
          </Field>
          <Field label="Sector">
            {(field) => (
              <Select {...field} value={sectorId} onChange={(event) => setSectorId(event.target.value)}>
                <option value="">None</option>
                {sectors.map((sector) => <option key={sector.id} value={sector.id}>{sector.name}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Website">
            {(field) => <Input {...field} type="url" value={website} onChange={(event) => setWebsite(event.target.value)} />}
          </Field>
        </div>
        <Field label="Description">
          {(field) => <Textarea {...field} value={description} onChange={(event) => setDescription(event.target.value)} />}
        </Field>
        <div className="flex gap-gap-md">
          <Button
            loading={update.isPending}
            disabled={!name.trim()}
            onClick={() => update.mutate(
              { input: { company_id: company.id, name, description: description || null, website_url: website || null, sector_id: sectorId || null } },
              { onSuccess: onDone },
            )}
          >
            Save company
          </Button>
          <Button variant="ghost" onClick={onDone}>Cancel</Button>
        </div>
      </CardBody>
    </Card>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-gap-lg">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-right text-foreground">{value}</dd>
    </div>
  );
}

/**
 * Merge, previewed.
 *
 * The dropped contacts are rendered as full records rather than counted,
 * because the duplicate often holds the current phone and designation while the
 * survivor's are stale — and nothing un-merges. That is exactly the payload the
 * generic summary table would flatten to "Contacts dropped: 1".
 */
function MergeAction({
  company,
  others,
  permission,
}: {
  company: CompanyPayload["company"];
  others: CompaniesPayload["companies"];
  permission: CompanyPayload["actions"]["merge"];
}) {
  const [duplicateId, setDuplicateId] = useState("");

  return (
    <PreviewConfirm
      command="merge_companies"
      input={{ survivor_id: company.id, duplicate_id: duplicateId }}
      title={`Merge into ${company.name}`}
      description="The duplicate is deactivated, its jobs and contacts repoint here, and nothing un-merges."
      confirmLabel="Merge"
      destructive
      choices={[
        {
          name: "duplicate_id",
          label: "Company to merge in",
          kind: "select",
          required: true,
          options: others.map((other) => ({ value: other.id, label: other.name })),
          hint: "This record is the survivor; the one you pick is absorbed.",
        },
      ]}
      renderSummary={(summary) => <MergeSummary summary={summary} />}
      trigger={
        <Button variant="secondary" disabled={!permission.allowed} title={permission.human ?? undefined}>
          Merge duplicate
        </Button>
      }
      onDone={() => setDuplicateId("")}
    />
  );
}

interface DroppedContact {
  id: string;
  name: string;
  email: string;
  phone: string | null;
  designation: string | null;
  is_primary: boolean;
}

function MergeSummary({ summary }: { summary: unknown }) {
  const merge = summary as {
    jobs: number;
    external_offers: number;
    contacts_repointed: number;
    contacts_dropped: DroppedContact[];
  };
  const dropped = merge.contacts_dropped ?? [];

  return (
    <div className="flex flex-col gap-gap-lg text-body-md">
      <dl className="grid grid-cols-2 gap-x-gap-lg gap-y-gap-tight">
        <dt className="text-muted-foreground">Jobs repointed</dt>
        <dd className="tabular text-foreground">{merge.jobs}</dd>
        <dt className="text-muted-foreground">External offers repointed</dt>
        <dd className="tabular text-foreground">{merge.external_offers}</dd>
        <dt className="text-muted-foreground">Contacts repointed</dt>
        <dd className="tabular text-foreground">{merge.contacts_repointed}</dd>
      </dl>

      {dropped.length > 0 ? (
        <div className="rounded border border-danger-border bg-danger-subtle p-gap-lg">
          <p className="text-body-md font-semibold text-danger">
            {dropped.length} contact{dropped.length === 1 ? "" : "s"} will be discarded
          </p>
          <p className="mt-gap-tight text-body-sm text-foreground">
            Their email already exists on {"the survivor"}. Nothing un-merges, so check
            whether the phone or designation below is the one you want to keep.
          </p>
          <ul className="mt-gap-lg flex flex-col gap-gap-md">
            {dropped.map((contact) => (
              <li key={contact.id} className="text-body-md text-foreground">
                <span className="font-medium">{contact.name}</span>
                <span className="text-body-sm text-muted-foreground">
                  {contact.is_primary ? " · primary" : " · not primary"}
                </span>
                <div className="text-body-sm text-muted-foreground">
                  {[contact.email, contact.phone, contact.designation]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-body-sm text-muted-foreground">
          No contact collides on email, so every one of them moves across.
        </p>
      )}
    </div>
  );
}

function AddContact({ companyId, onDone }: { companyId: string; onDone: () => void }) {
  const create = useCommand("contact_create");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [designation, setDesignation] = useState("");
  const [isPrimary, setIsPrimary] = useState(false);

  return (
    <div className="flex flex-col gap-gap-lg">
      {create.isError ? <ErrorState error={create.error} title="Could not add contact" /> : null}
      <div className="grid gap-gap-lg sm:grid-cols-2">
        <Field label="Name" required>
          {(field) => (
            <Input {...field} value={name} onChange={(event) => setName(event.target.value)} />
          )}
        </Field>
        <Field label="Email" required>
          {(field) => (
            <Input
              {...field}
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          )}
        </Field>
        <Field label="Phone">
          {(field) => (
            <Input {...field} value={phone} onChange={(event) => setPhone(event.target.value)} />
          )}
        </Field>
        <Field label="Designation">
          {(field) => (
            <Input
              {...field}
              value={designation}
              onChange={(event) => setDesignation(event.target.value)}
            />
          )}
        </Field>
      </div>
      <label className="flex items-center gap-gap-md text-body-md text-foreground">
        <Checkbox
          checked={isPrimary}
          onChange={(event) => setIsPrimary(event.target.checked)}
        />
        Make this the primary contact
      </label>
      <div className="flex items-center gap-gap-md">
        <Button
          variant="primary"
          disabled={!name.trim() || !email.trim()}
          loading={create.isPending}
          onClick={() =>
            create.mutate(
              {
                input: {
                  company_id: companyId,
                  name: name.trim(),
                  email: email.trim(),
                  phone: phone.trim() || null,
                  designation: designation.trim() || null,
                  is_primary: isPrimary,
                },
              },
              { onSuccess: onDone },
            )
          }
        >
          Add contact
        </Button>
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function ContactActions({ companyId, contact }: { companyId: string; contact: Contact }) {
  const update = useCommand("contact_update");
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(contact.name);
  const [email, setEmail] = useState(contact.email);
  const [phone, setPhone] = useState(contact.phone ?? "");
  const [designation, setDesignation] = useState(contact.designation ?? "");
  const [primary, setPrimary] = useState(contact.is_primary);
  if (editing) {
    return (
      <div className="min-w-72 space-y-gap-md text-left">
        {update.isError ? <ErrorState error={update.error} title="Could not update contact" /> : null}
        <Input aria-label="Contact name" value={name} onChange={(event) => setName(event.target.value)} />
        <Input aria-label="Contact email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        <Input aria-label="Contact phone" value={phone} onChange={(event) => setPhone(event.target.value)} />
        <Input aria-label="Contact designation" value={designation} onChange={(event) => setDesignation(event.target.value)} />
        <label className="flex items-center gap-gap-md text-body-sm text-foreground">
          <Checkbox checked={primary} onChange={(event) => setPrimary(event.target.checked)} />
          Primary contact
        </label>
        <div className="flex justify-end gap-gap-md">
          <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>Cancel</Button>
          <Button
            size="sm"
            loading={update.isPending}
            disabled={!name.trim() || !email.trim()}
            onClick={() => update.mutate(
              { input: { company_id: companyId, contact_id: contact.id, name, email, phone: phone || null, designation: designation || null, is_primary: primary } },
              { onSuccess: () => setEditing(false) },
            )}
          >
            Save
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="flex justify-end gap-gap-tight">
      <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>Edit</Button>
      <PreviewConfirm
        command="contact_delete"
        input={{ company_id: companyId, contact_id: contact.id }}
        title={`Delete ${contact.name}?`}
        description="Deleting a primary contact promotes nobody — the company simply has none."
        confirmLabel="Delete contact"
        destructive
        trigger={<Button variant="destructive-ghost" size="sm">Delete</Button>}
      />
    </div>
  );
}

function ContactTable({
  companyId,
  contacts,
}: {
  companyId: string;
  contacts: Contact[];
}) {
  const columns: Column<Contact>[] = [
    {
      key: "name",
      header: "Name",
      cell: (contact) => (
        <div className="flex flex-col">
          <span className="text-foreground">
            {contact.name}
            {contact.is_primary ? (
              <span className="ml-gap-md text-body-sm text-muted-foreground">Primary</span>
            ) : null}
          </span>
          <span className="text-body-sm text-muted-foreground">{contact.email}</span>
        </div>
      ),
    },
    {
      key: "designation",
      header: "Designation",
      cell: (contact) =>
        contact.designation ?? <span className="text-muted-foreground">—</span>,
    },
    {
      key: "phone",
      header: "Phone",
      cell: (contact) => contact.phone ?? <span className="text-muted-foreground">—</span>,
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      numeric: true,
      cell: (contact) => <ContactActions companyId={companyId} contact={contact} />,
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={contacts}
      rowKey={(contact) => contact.id}
      empty={
        <CardBody>
          <EmptyState message="No contacts recorded for this company." />
        </CardBody>
      }
    />
  );
}
