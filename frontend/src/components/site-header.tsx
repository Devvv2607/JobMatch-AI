import Link from "next/link";

type Page = "matches" | "profile";

const LINKS: { page: Page; href: string; label: string }[] = [
  { page: "matches", href: "/matches", label: "Matches" },
  { page: "profile", href: "/profile", label: "Profile" },
];

/** The skip link and the top bar, shared by every signed-in screen. */
export function SiteHeader({ current, skipLabel, nav = true }: { current?: Page; skipLabel: string; nav?: boolean }) {
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-10 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2"
      >
        {skipLabel}
      </a>
      <header className="border-b border-rule">
        <div className="mx-auto flex h-14 w-full max-w-4xl items-center justify-between gap-4 px-4 sm:px-6">
          <Link href="/" className="font-serif text-lg">
            JobMatch
          </Link>
          {nav && (
            <nav aria-label="Main">
              <ul className="flex gap-5 text-sm">
                {LINKS.map((link) => (
                  <li key={link.page}>
                    <Link
                      href={link.href}
                      aria-current={current === link.page ? "page" : undefined}
                      className={`inline-flex min-h-11 items-center underline-offset-[6px] ${
                        current === link.page ? "underline decoration-accent decoration-2" : "hover:underline"
                      }`}
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          )}
        </div>
      </header>
    </>
  );
}
