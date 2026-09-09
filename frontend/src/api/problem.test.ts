import { describe, expect, it } from "vitest";

import { toApiError } from "@/api/problem";

describe("API correlation references", () => {
  it("retains the response request ID on API errors", async () => {
    const error = await toApiError(
      new Response(JSON.stringify({ title: "Failed", status: 500, type: "about:blank" }), {
        status: 500,
        headers: {
          "content-type": "application/problem+json",
          "x-request-id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        },
      }),
    );

    expect(error.requestId).toBe("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
  });
});
