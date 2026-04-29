(*
  motor_start.st
  Simple motor start with fault interlock.
  X0 = start command
  X1 = fault sensor (stops motor if active)
  Y0 = motor output
*)

IF X0 AND NOT X1 THEN
    Y0 := TRUE;
ELSE
    Y0 := FALSE;
END_IF;
