import type { Metadata } from "next";

import { Profile } from "@/components/profile/profile-screen";

export const metadata: Metadata = { title: "Your profile · JobMatch" };

export default function ProfilePage() {
  return <Profile />;
}
