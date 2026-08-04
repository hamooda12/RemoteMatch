import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  ApiError,
  apiMutation,
  apiRequest,
  clearCsrfToken,
} from "./api-client";

describe("api client", () => {
  beforeEach(() => {
    clearCsrfToken();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends JSON requests with authenticated cookies", async () => {
    const fetchMock = vi.fn<typeof fetch>();

    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "ok",
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    vi.stubGlobal("fetch", fetchMock);

    const response = await apiRequest<{
      status: string;
    }>("/health", {
      method: "POST",
      body: JSON.stringify({
        example: true,
      }),
    });

    expect(response).toEqual({
      status: "ok",
    });

    expect(fetchMock).toHaveBeenCalledOnce();

    const requestOptions =
      fetchMock.mock.calls[0]?.[1];

    expect(requestOptions?.credentials).toBe("include");

    const headers = new Headers(
      requestOptions?.headers,
    );

    expect(headers.get("Accept")).toBe(
      "application/json",
    );

    expect(headers.get("Content-Type")).toBe(
      "application/json",
    );
  });

  it("converts API error details into ApiError", async () => {
    const fetchMock = vi.fn<typeof fetch>();

    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "Invalid email or password.",
        }),
        {
          status: 401,
          statusText: "Unauthorized",
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    vi.stubGlobal("fetch", fetchMock);

    try {
      await apiRequest("/auth/login");
      throw new Error("Expected the request to fail.");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({
        status: 401,
        message: "Invalid email or password.",
      });
    }
  });

  it("formats Pydantic validation errors", async () => {
    const fetchMock = vi.fn<typeof fetch>();

    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: [
            {
              msg: "Field required",
            },
            {
              msg: "Value is invalid",
            },
          ],
        }),
        {
          status: 422,
          headers: {
            "Content-Type": "application/json",
          },
        },
      ),
    );

    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiRequest("/profile"),
    ).rejects.toMatchObject({
      status: 422,
      message: "Field required Value is invalid",
    });
  });

  it("retrieves and attaches a CSRF token", async () => {
    const fetchMock = vi.fn<typeof fetch>();

    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            csrf_token: "test-csrf-token",
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json",
            },
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            message: "Saved",
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json",
            },
          },
        ),
      );

    vi.stubGlobal("fetch", fetchMock);

    await apiMutation("/profile", {
      method: "PUT",
      body: JSON.stringify({
        location: "Bethlehem",
      }),
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);

    const mutationOptions =
      fetchMock.mock.calls[1]?.[1];

    const mutationHeaders = new Headers(
      mutationOptions?.headers,
    );

    expect(
      mutationHeaders.get("X-CSRF-Token"),
    ).toBe("test-csrf-token");
  });
});