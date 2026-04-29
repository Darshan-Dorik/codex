(*
  shuttle_control.st
  Shuttle movement control with position sensor and jam detection.
  X0 = run command
  X1 = position sensor (shuttle reached threshold)
  X2 = jam sensor
  Y0 = shuttle motor
  Y1 = position reached indicator
*)

IF X0 AND NOT X2 THEN
    Y0 := TRUE;
ELSE
    Y0 := FALSE;
END_IF;

IF X1 THEN
    Y1 := TRUE;
ELSE
    Y1 := FALSE;
END_IF;
