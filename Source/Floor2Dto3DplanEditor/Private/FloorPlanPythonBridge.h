// Copyright Epic Games, Inc. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "PythonScriptTypes.h"

class FJsonValue;

/** One line of output captured while a Python statement ran. */
struct FFloorPlanPythonLogLine
{
	FString Text;
	EPythonLogOutputType Type = EPythonLogOutputType::Info;
};

/** Outcome of one Python call made through the bridge. */
struct FFloorPlanPythonResult
{
	/** False when the plugin is missing or the statement raised. */
	bool bSucceeded = false;
	/** False only when the Python plugin itself is unavailable. */
	bool bPythonAvailable = true;
	/** Python repr of the evaluated expression's value (or the error text). */
	FString Result;
	TArray<FFloorPlanPythonLogLine> Log;
};

/**
 * Thin wrapper over the Python Editor Script Plugin shared by the Floor Plan
 * Import panel and the Wall Correction window. Everything the panels need
 * from Python goes through `floorplan_panel.py`, which returns either plain
 * ints or base64-encoded JSON so values survive Python's repr().
 */
namespace FloorPlanPython
{
	FFloorPlanPythonResult Exec(const FString& Command, bool bShowProgress, const FText& ProgressText);

	/** Strips the quotes Python's repr() wraps around a returned str. */
	FString UnquoteResult(const FString& Result);

	/** Decodes a str result holding base64(JSON) into a JSON value. */
	bool DecodePayload(const FString& Result, TSharedPtr<FJsonValue>& OutValue);

	/** Wraps a string as a single-quoted Python literal, escaping what Python would interpret. */
	FString ToPythonLiteral(const FString& Value);

	/** Parses an int result; 0 when empty or unparsable. */
	int32 ResultToInt(const FString& Result);
}
