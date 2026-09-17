// Copyright Epic Games, Inc. All Rights Reserved.

#include "FloorPlanPythonBridge.h"

#include "Dom/JsonValue.h"
#include "IPythonScriptPlugin.h"
#include "Misc/Base64.h"
#include "Misc/ScopedSlowTask.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace FloorPlanPython
{
	FFloorPlanPythonResult Exec(const FString& Command, const bool bShowProgress, const FText& ProgressText)
	{
		FFloorPlanPythonResult Outcome;

		IPythonScriptPlugin* Python = IPythonScriptPlugin::Get();
		if (!Python || !Python->IsPythonAvailable())
		{
			Outcome.bPythonAvailable = false;
			Outcome.Result = TEXT("Python is not available. Enable the Python Editor Script Plugin, then restart the editor.");
			return Outcome;
		}

		FPythonCommandEx PythonCommand;
		PythonCommand.ExecutionMode = EPythonCommandExecutionMode::EvaluateStatement;
		PythonCommand.Command = Command;

		if (bShowProgress)
		{
			FScopedSlowTask SlowTask(1.0f, ProgressText);
			SlowTask.MakeDialog();
			SlowTask.EnterProgressFrame(1.0f);
			Outcome.bSucceeded = Python->ExecPythonCommandEx(PythonCommand);
		}
		else
		{
			Outcome.bSucceeded = Python->ExecPythonCommandEx(PythonCommand);
		}

		Outcome.Log.Reserve(PythonCommand.LogOutput.Num());
		for (const FPythonLogOutputEntry& Entry : PythonCommand.LogOutput)
		{
			Outcome.Log.Add({ Entry.Output, Entry.Type });
		}
		Outcome.Result = PythonCommand.CommandResult;
		return Outcome;
	}

	FString UnquoteResult(const FString& Result)
	{
		FString Text = Result;
		Text.TrimStartAndEndInline();
		Text.TrimCharInline(TEXT('\''), /*bCharRemoved*/ nullptr);
		Text.TrimCharInline(TEXT('"'), /*bCharRemoved*/ nullptr);
		return Text;
	}

	bool DecodePayload(const FString& Result, TSharedPtr<FJsonValue>& OutValue)
	{
		const FString Encoded = UnquoteResult(Result);
		if (Encoded.IsEmpty())
		{
			return false;
		}

		TArray<uint8> Bytes;
		if (!FBase64::Decode(Encoded, Bytes))
		{
			return false;
		}
		Bytes.Add(0);

		const FString Json = FString(UTF8_TO_TCHAR(reinterpret_cast<const ANSICHAR*>(Bytes.GetData())));
		const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
		return FJsonSerializer::Deserialize(Reader, OutValue) && OutValue.IsValid();
	}

	FString ToPythonLiteral(const FString& Value)
	{
		FString Escaped = Value;
		Escaped.ReplaceInline(TEXT("\\"), TEXT("\\\\"), ESearchCase::CaseSensitive);
		Escaped.ReplaceInline(TEXT("'"), TEXT("\\'"), ESearchCase::CaseSensitive);
		Escaped.ReplaceInline(TEXT("\r"), TEXT(""), ESearchCase::CaseSensitive);
		Escaped.ReplaceInline(TEXT("\n"), TEXT("\\n"), ESearchCase::CaseSensitive);
		return FString::Printf(TEXT("'%s'"), *Escaped);
	}

	int32 ResultToInt(const FString& Result)
	{
		return FCString::Atoi(*UnquoteResult(Result));
	}
}
