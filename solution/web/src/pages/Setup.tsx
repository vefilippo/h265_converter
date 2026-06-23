import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";

interface SetupProps {
  onDone: () => void;
}

export default function Setup({ onDone: _onDone }: SetupProps) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Set up H.265 Transcoder</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted">Let's get you configured.</p>
        </CardContent>
      </Card>
    </div>
  );
}
