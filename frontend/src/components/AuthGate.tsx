import { useState, type ReactNode } from "react";

import { devLogin, type Me } from "@/api/client";
import { useMe } from "@/api/useScreen";
import { Button } from "./ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/card";
import { Field } from "./ui/field";
import { Input } from "./ui/input";
import { ErrorState, Skeleton } from "./ui/states";

/**
 * Sign-in gate.
 *
 * Google is the only real sign-in; the dev-login form appears only when the
 * `/me` bootstrap says `dev_login_enabled`, which is the server's flag, not a
 * build-time constant. There is no client-side authorisation here beyond
 * showing or hiding — the server decides (LLD §16).
 */
export function AuthGate({ children }: { children: (me: Me) => ReactNode }) {
  const bootstrap = useMe();

  if (bootstrap.isPending) {
    return (
      <div className="flex flex-col gap-gap-lg p-container-padding">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (bootstrap.isError) {
    return (
      <div className="p-container-padding">
        <ErrorState error={bootstrap.error} onRetry={() => void bootstrap.refetch()} />
      </div>
    );
  }
  if (!bootstrap.data.authenticated) {
    return <SignIn devLoginEnabled={bootstrap.data.dev_login_enabled} />;
  }
  return <>{children(bootstrap.data)}</>;
}

function SignIn({ devLoginEnabled }: { devLoginEnabled: boolean }) {
  const [email, setEmail] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submitDevLogin(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await devLogin(email);
      window.location.reload();
    } catch (caught) {
      setError(caught);
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-container-padding">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
        </CardHeader>
        <CardBody className="flex flex-col gap-gap-lg">
          <Button variant="primary" className="w-full" asChild>
            <a href="/auth/google/login">Continue with Google</a>
          </Button>

          {devLoginEnabled ? (
            <>
              <div className="flex items-center gap-gap-md">
                <span className="h-px flex-1 bg-border" />
                <span className="text-label-caps uppercase text-muted-foreground">
                  Development only
                </span>
                <span className="h-px flex-1 bg-border" />
              </div>
              <form className="flex flex-col gap-gap-lg" onSubmit={submitDevLogin}>
                <Field label="Email" required>
                  {(field) => (
                    <Input
                      {...field}
                      type="email"
                      autoComplete="username"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                    />
                  )}
                </Field>
                <Button type="submit" variant="secondary" loading={pending} disabled={!email}>
                  Sign in as this user
                </Button>
              </form>
              {error ? <ErrorState error={error} title="Sign-in failed" /> : null}
            </>
          ) : null}
        </CardBody>
      </Card>
    </div>
  );
}
