import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("frontend test environment", () => {
  it("renders an accessible RemoteMatch heading", () => {
    render(
      <main>
        <h1>RemoteMatch</h1>
      </main>,
    );

    expect(
      screen.getByRole("heading", {
        name: "RemoteMatch",
      }),
    ).toBeInTheDocument();
  });
});