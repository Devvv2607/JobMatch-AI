import type { Metadata } from "next";

import { Profile } from "@/components/profile/profile-screen";

export const metadata: Metadata = { title: "Your profile · JobMatch" };

export default async function ProfilePage({ searchParams }: { searchParams: Promise<{ edit?: string }> }) {
  const { edit } = await searchParams;
  return <Profile editRule={edit} />;
}
