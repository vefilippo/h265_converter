import { Spinner } from "../components/ui/spinner";
import Login from "../pages/Login";
import Setup from "../pages/Setup";
import { useMe } from "./useMe";

interface AuthGateProps {
  children: React.ReactNode;
}

export function AuthGate({ children }: AuthGateProps) {
  const { data, isLoading, refetch } = useMe();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-bg">
        <Spinner size="lg" />
      </div>
    );
  }

  if (data?.needs_setup) {
    return <Setup onDone={() => refetch()} />;
  }

  if (!data?.authed) {
    return <Login onSuccess={() => refetch()} />;
  }

  return <>{children}</>;
}
