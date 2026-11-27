import Image from "next/image";

/** The company's logo when we have one; otherwise its initial on a tinted square. */
export function CompanyMark({ company, logoUrl }: { company: string; logoUrl?: string | null }) {
  if (logoUrl) {
    return (
      <Image
        src={logoUrl}
        alt=""
        width={32}
        height={32}
        unoptimized
        className="size-8 shrink-0 rounded-sm border border-rule bg-surface object-contain"
      />
    );
  }
  const initial = company.trim().charAt(0).toUpperCase() || "?";
  return (
    <span
      aria-hidden="true"
      data-testid="company-monogram"
      className="flex size-8 shrink-0 items-center justify-center rounded-sm bg-accent-soft font-serif text-base text-accent"
    >
      {initial}
    </span>
  );
}
