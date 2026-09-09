import { useMemo, useState } from "react";

import type { JobQuestion, ResumeChoice } from "@/api/payloads";
import { useCommand } from "@/api/useScreen";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select, Textarea } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/states";

interface BaseProps {
  questions: JobQuestion[];
  resumes: ResumeChoice[];
  initialAnswers?: { question_id: string; value: unknown }[];
  initialResumeUrl?: string;
  submitLabel: string;
  pending: boolean;
  error: unknown;
  onSubmit: (submission: FormSubmission) => void;
  onCancel?: () => void;
}

interface FormSubmission {
  answers: { question_id: string; value: unknown }[];
  resume_id: string | null;
  resume_url: string | null;
}

export function ApplyApplicationForm({
  cycleId,
  jobId,
  enrollmentId,
  questions,
  resumes,
}: {
  cycleId: string;
  jobId: string;
  enrollmentId: string;
  questions: JobQuestion[];
  resumes: ResumeChoice[];
}) {
  const apply = useCommand("apply");
  return (
    <ApplicationFields
      questions={questions}
      resumes={resumes}
      submitLabel="Apply"
      pending={apply.isPending}
      error={apply.error}
      onSubmit={(submission) =>
        apply.mutate({
          input: {
            cycle_id: cycleId,
            job_id: jobId,
            enrollment_id: enrollmentId,
            ...submission,
          },
        })
      }
    />
  );
}

export function EditApplicationForm({
  cycleId,
  enrollmentId,
  applicationId,
  questions,
  answers,
  resumes,
  resumeUrl,
  onDone,
}: {
  cycleId: string;
  enrollmentId: string;
  applicationId: string;
  questions: JobQuestion[];
  answers: { question_id: string; value: unknown }[];
  resumes: ResumeChoice[];
  resumeUrl: string;
  onDone: () => void;
}) {
  const edit = useCommand("edit_application");
  return (
    <ApplicationFields
      questions={questions}
      resumes={resumes}
      initialAnswers={answers}
      initialResumeUrl={resumeUrl}
      submitLabel="Save application"
      pending={edit.isPending}
      error={edit.error}
      onCancel={onDone}
      onSubmit={(submission) =>
        edit.mutate(
          {
            input: {
              cycle_id: cycleId,
              enrollment_id: enrollmentId,
              application_id: applicationId,
              ...submission,
            },
          },
          { onSuccess: onDone },
        )
      }
    />
  );
}

function ApplicationFields({
  questions,
  resumes,
  initialAnswers = [],
  initialResumeUrl,
  submitLabel,
  pending,
  error,
  onSubmit,
  onCancel,
}: BaseProps) {
  const initial = useMemo(
    () => Object.fromEntries(initialAnswers.map((answer) => [answer.question_id, answer.value])),
    [initialAnswers],
  );
  const matchingResume = resumes.find((resume) => resume.drive_url === initialResumeUrl);
  const preferredResume =
    matchingResume ??
    resumes.find((resume) => resume.is_cycle_default) ??
    resumes.find((resume) => resume.is_default) ??
    resumes[0];
  const [answers, setAnswers] = useState<Record<string, unknown>>(initial);
  const [resumeChoice, setResumeChoice] = useState(
    preferredResume?.id ?? (initialResumeUrl ? "__url" : ""),
  );
  const [oneOffUrl, setOneOffUrl] = useState(
    matchingResume ? "" : (initialResumeUrl ?? ""),
  );

  const requiredMissing = questions.some((question) =>
    question.required ? blank(answers[question.question_id]) : false,
  );
  const resumeMissing = resumeChoice === "" || (resumeChoice === "__url" && !oneOffUrl.trim());

  function update(questionId: string, value: unknown) {
    setAnswers((current) => ({ ...current, [questionId]: value }));
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (requiredMissing || resumeMissing) return;
    onSubmit({
      answers: questions
        .filter((question) => !blank(answers[question.question_id]))
        .map((question) => ({
          question_id: question.question_id,
          value: answers[question.question_id],
        })),
      resume_id: resumeChoice !== "__url" ? resumeChoice : null,
      resume_url: resumeChoice === "__url" ? oneOffUrl.trim() : null,
    });
  }

  return (
    <form className="flex flex-col gap-gap-lg" onSubmit={submit}>
      {error ? <ErrorState error={error} title="Could not save the application" /> : null}
      <Field label="Resume" required hint="Choose a saved resume or use one Drive link just for this application.">
        {(field) => (
          <Select
            {...field}
            value={resumeChoice}
            onChange={(event) => setResumeChoice(event.target.value)}
          >
            <option value="">Select a resume…</option>
            {resumes.map((resume) => (
              <option key={resume.id} value={resume.id}>
                {resume.label}
                {resume.is_cycle_default ? " — cycle default" : resume.is_default ? " — default" : ""}
              </option>
            ))}
            <option value="__url">Use a one-off Drive link</option>
          </Select>
        )}
      </Field>
      {resumeChoice === "__url" ? (
        <Field label="One-off resume URL" required hint="A Google Drive or Docs file link.">
          {(field) => (
            <Input
              {...field}
              type="url"
              value={oneOffUrl}
              onChange={(event) => setOneOffUrl(event.target.value)}
            />
          )}
        </Field>
      ) : null}

      {questions.map((question) => (
        <QuestionField
          key={question.question_id}
          question={question}
          value={answers[question.question_id]}
          onChange={(value) => update(question.question_id, value)}
        />
      ))}

      <div className="flex items-center gap-gap-md">
        {onCancel ? (
          <Button type="button" variant="ghost" onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
        ) : null}
        <Button type="submit" loading={pending} disabled={requiredMissing || resumeMissing}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

function QuestionField({
  question,
  value,
  onChange,
}: {
  question: JobQuestion;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const props = { label: question.text, ...(question.required ? { required: true } : {}) };
  if (question.qtype === "longtext") {
    return (
      <Field {...props}>
        {(field) => (
          <Textarea {...field} value={typeof value === "string" ? value : ""} onChange={(event) => onChange(event.target.value)} />
        )}
      </Field>
    );
  }
  if (question.qtype === "single") {
    return (
      <Field {...props}>
        {(field) => (
          <Select {...field} value={typeof value === "string" ? value : ""} onChange={(event) => onChange(event.target.value)}>
            <option value="">Select…</option>
            {question.options.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </Select>
        )}
      </Field>
    );
  }
  if (question.qtype === "multi") {
    const selected = Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
    return (
      <fieldset className="flex flex-col gap-gap-tight">
        <legend className="text-body-sm font-semibold text-foreground">
          {question.text}{question.required ? (
            <>
              {" "}
              <span className="text-danger">*</span>
            </>
          ) : null}
        </legend>
        <div className="flex flex-wrap gap-gap-lg rounded border border-border p-gap-md">
          {question.options.map((option) => (
            <label key={option} className="flex items-center gap-gap-md text-body-md text-foreground">
              <Checkbox
                checked={selected.includes(option)}
                onChange={(event) => onChange(event.target.checked ? [...selected, option] : selected.filter((item) => item !== option))}
              />
              {option}
            </label>
          ))}
        </div>
      </fieldset>
    );
  }
  if (question.qtype === "boolean") {
    return (
      <Field {...props}>
        {(field) => (
          <Select
            {...field}
            value={typeof value === "boolean" ? String(value) : ""}
            onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value === "true")}
          >
            <option value="">Select…</option>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </Select>
        )}
      </Field>
    );
  }
  const inputType: React.HTMLInputTypeAttribute =
    question.qtype === "number" || question.qtype === "date" || question.qtype === "email" || question.qtype === "url"
      ? question.qtype
      : "text";
  return (
    <Field {...props}>
      {(field) => (
        <Input
          {...field}
          type={inputType}
          value={typeof value === "string" || typeof value === "number" ? String(value) : ""}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </Field>
  );
}

function blank(value: unknown): boolean {
  return value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0);
}
