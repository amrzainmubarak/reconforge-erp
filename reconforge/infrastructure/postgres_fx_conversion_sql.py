"""Additive exact inverse of captured FX rates; existing FX1 SQL is unchanged."""

UPGRADE_SQL = r"""
CREATE FUNCTION reconforge.fx_convert_inverse(amount NUMERIC,rate NUMERIC,fp INTEGER,lp INTEGER)
RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE SET search_path=pg_catalog AS $fx_inverse$
DECLARE coefficient NUMERIC;numerator NUMERIC;quotient NUMERIC;remainder NUMERIC;result NUMERIC;
BEGIN
 IF amount IS NULL OR rate IS NULL OR fp IS NULL OR lp IS NULL
 OR amount::text !~ '^-?(0|[1-9][0-9]*)$' OR abs(amount)>9000000000000000000
 OR rate::text !~ '^(0|[1-9][0-9]{0,11})(\.[0-9]{1,12})?$' OR rate<=0
 OR fp NOT BETWEEN 0 AND 8 OR lp NOT BETWEEN 0 AND 8 THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fx_inverse_conversion',
   MESSAGE='Inverse FX requires bounded exact minor units, positive original rate and captured currency precisions';
 END IF;
 -- Twelve rate decimal places make both operands integers. NUMERIC division
 -- followed by round() can round a near-half quotient twice; div/mod cannot.
 coefficient:=rate*1000000000000;
 numerator:=abs(amount)*power(10::numeric,lp-fp+12);
 quotient:=div(numerator,coefficient);remainder:=mod(numerator,coefficient);
 result:=sign(amount)*(quotient+CASE WHEN remainder*2>=coefficient THEN 1 ELSE 0 END);
 IF abs(result)>9000000000000000000 THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='fx_inverse_conversion',
   MESSAGE='Inverse FX result exceeds the native minor-unit bound';
 END IF;
 RETURN result;
END $fx_inverse$;
"""

DOWNGRADE_SQL = "DROP FUNCTION reconforge.fx_convert_inverse(NUMERIC,NUMERIC,INTEGER,INTEGER);"
