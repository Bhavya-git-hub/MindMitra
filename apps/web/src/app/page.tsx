import { redirect } from "next/navigation";

/** The proxy sends people to their portal or /login; this is the fallback. */
export default function HomePage() {
  redirect("/login");
}
