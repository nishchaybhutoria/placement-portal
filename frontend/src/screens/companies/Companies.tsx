import { Building2, Plus, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { payload, type CompaniesPayload } from "@/api/payloads";
import { useCommand, useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select, Textarea } from "@/components/ui/input";
import { DataTable, type Column } from "@/components/ui/table";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from "@/lib/useDebouncedValue";

type Company = CompaniesPayload["companies"][number];

/** The company directory (Behavior CMP, LLD §11.3 `staff/companies`). */
export function Companies() {
  const [q, setQ] = useState("");
  const [sectorId, setSectorId] = useState("");
  const [includeInactive, setIncludeInactive] = useState(false);
  const [creating, setCreating] = useState(false);

  const search = useDebouncedValue(q.trim(), SEARCH_DEBOUNCE_MS);
  const screen = useScreen("staff/companies", {
    query: {
      ...(search ? { q: search } : {}),
      ...(sectorId ? { sector_id: sectorId } : {}),
      include_inactive: includeInactive,
    },
    keepPrevious: true,
  });

  const data = screen.data ? payload<CompaniesPayload>(screen.data) : undefined;

  const columns: Column<Company>[] = [
    {
      key: "name",
      header: "Company",
      cell: (company) => (
        <div className="flex flex-col">
          <Link
            to={`/staff/companies/${company.id}`}
            className="font-medium text-accent hover:underline"
          >
            {company.name}
          </Link>
          {company.website_url ? (
            <span className="text-body-sm text-muted-foreground">{company.website_url}</span>
          ) : null}
        </div>
      ),
    },
    {
      key: "sector",
      header: "Sector",
      cell: (company) =>
        company.sector?.name ?? <span className="text-muted-foreground">—</span>,
    },
    {
      key: "contact",
      header: "Primary contact",
      cell: (company) =>
        company.primary_contact ? (
          <div className="flex flex-col">
            <span className="text-foreground">{company.primary_contact.name}</span>
            <span className="text-body-sm text-muted-foreground">
              {company.primary_contact.email}
            </span>
          </div>
        ) : (
          <span className="text-muted-foreground">None</span>
        ),
    },
    { key: "jobs", header: "Jobs", numeric: true, cell: (company) => company.job_count },
    {
      key: "state",
      header: "State",
      cell: (company) =>
        company.is_active ? "Active" : <span className="text-muted-foreground">Inactive</span>,
    },
  ];

  return (
    <>
      <PageHeader
        title="Companies"
        subtitle="Every recruiter on record, with the contacts and jobs attached to them."
        actions={
          <Button
            variant="primary"
            icon={<Plus className="h-4 w-4" />}
            onClick={() => setCreating((open) => !open)}
          >
            New company
          </Button>
        }
      />

      {creating ? (
        <CreateCompanyCard
          sectors={data?.sectors ?? []}
          onDone={() => setCreating(false)}
        />
      ) : null}

      <Card>
        <CardHeader className="flex-wrap">
          <CardTitle>Directory</CardTitle>
          <div className="flex flex-wrap items-center gap-gap-md">
            <div className="relative">
              <Search
                aria-hidden
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                aria-label="Search by name"
                className="w-64 pl-9"
                placeholder="Search by name"
                value={q}
                onChange={(event) => setQ(event.target.value)}
              />
            </div>
            <Select
              aria-label="Filter by sector"
              className="w-48"
              value={sectorId}
              onChange={(event) => setSectorId(event.target.value)}
            >
              <option value="">All sectors</option>
              {(data?.sectors ?? []).map((sector) => (
                <option key={sector.id} value={sector.id}>
                  {sector.name}
                </option>
              ))}
            </Select>
            <label className="flex items-center gap-gap-md text-body-md text-foreground">
              <Checkbox
                checked={includeInactive}
                onChange={(event) => setIncludeInactive(event.target.checked)}
              />
              Include inactive
            </label>
          </div>
        </CardHeader>

        {screen.isPending ? (
          <TableSkeleton />
        ) : screen.isError ? (
          <CardBody>
            <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />
          </CardBody>
        ) : (
          <DataTable
            columns={columns}
            rows={data?.companies ?? []}
            rowKey={(company) => company.id}
            empty={
              <CardBody>
                <EmptyState
                  icon={<Building2 className="h-8 w-8" />}
                  message={
                    q || sectorId
                      ? "No company matches those filters."
                      : "No companies yet. Add the first one."
                  }
                />
              </CardBody>
            }
          />
        )}
      </Card>
    </>
  );
}

function CreateCompanyCard({
  sectors,
  onDone,
}: {
  sectors: CompaniesPayload["sectors"];
  onDone: () => void;
}) {
  const create = useCommand("create_company");
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [sectorId, setSectorId] = useState("");
  const [description, setDescription] = useState("");

  return (
    <Card>
      <CardHeader>
        <CardTitle>New company</CardTitle>
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        {create.isError ? <ErrorState error={create.error} title="Could not create" /> : null}
        <div className="grid gap-gap-lg sm:grid-cols-2">
          <Field label="Name" required>
            {(field) => (
              <Input
                {...field}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            )}
          </Field>
          <Field
            label="Website"
            hint="https only — a directory link handed to students must not downgrade."
          >
            {(field) => (
              <Input
                {...field}
                type="url"
                placeholder="https://example.com"
                value={website}
                onChange={(event) => setWebsite(event.target.value)}
              />
            )}
          </Field>
          <Field label="Sector">
            {(field) => (
              <Select
                {...field}
                value={sectorId}
                onChange={(event) => setSectorId(event.target.value)}
              >
                <option value="">No sector</option>
                {sectors.map((sector) => (
                  <option key={sector.id} value={sector.id}>
                    {sector.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>
        <Field label="Description">
          {(field) => (
            <Textarea
              {...field}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          )}
        </Field>
        <div className="flex items-center gap-gap-md">
          <Button
            variant="primary"
            disabled={!name.trim()}
            loading={create.isPending}
            onClick={() =>
              create.mutate(
                {
                  input: {
                    name: name.trim(),
                    website_url: website.trim() || null,
                    sector_id: sectorId || null,
                    description: description.trim() || null,
                  },
                },
                { onSuccess: onDone },
              )
            }
          >
            Create company
          </Button>
          <Button variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
