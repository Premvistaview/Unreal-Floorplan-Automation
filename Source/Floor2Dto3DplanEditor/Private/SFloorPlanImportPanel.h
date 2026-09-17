// Copyright Epic Games, Inc. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Views/SListView.h"

/** Severity used to colour a line in the panel's log. */
enum class EFloorPlanLogSeverity : uint8
{
	Info,
	Warning,
	Error,
	Success
};

/** One line in the panel's log view. */
struct FFloorPlanLogLine
{
	FFloorPlanLogLine(FString InText, const EFloorPlanLogSeverity InSeverity)
		: Text(MoveTemp(InText))
		, Severity(InSeverity)
	{
	}

	FString Text;
	EFloorPlanLogSeverity Severity;
};

/**
 * Dockable panel that drives detection.
 *
 * Detection and actor staging stay in Python; this panel collects the
 * settings, runs the bridge module, and mirrors the Python log locally so the
 * user never has to dig through the Output Log. When detection succeeds it
 * imports the plan image into the project and opens the Wall Correction
 * window, where the result is reviewed and fixed by hand.
 */
class SFloorPlanImportPanel : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SFloorPlanImportPanel) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

private:
	TSharedRef<SWidget> BuildSourceSection();
	TSharedRef<SWidget> BuildSettingsSection();
	TSharedRef<SWidget> BuildActionSection();
	TSharedRef<SWidget> BuildLogSection();

	TSharedRef<ITableRow> OnGenerateLogRow(
		TSharedPtr<FFloorPlanLogLine> Item,
		const TSharedRef<STableViewBase>& OwnerTable);

	FReply OnBrowseClicked();
	FReply OnBrowseOdaClicked();
	FReply OnGenerateClicked();
	FReply OnOpenCorrectionClicked();
	FReply OnClearLogClicked();
	FReply OnCopyLogClicked();

	bool CanGenerate() const;

	/** Appends text to the log, splitting embedded newlines into separate rows. */
	void AppendLog(const FString& Text, EFloorPlanLogSeverity Severity);

	/** Runs a Python statement, mirrors captured output into the panel log, and returns the result text. */
	bool ExecPython(const FString& Command, const FText& SlowTaskText, FString& OutResult);

	/** Runs the Python bridge and mirrors its captured output into the log. */
	void RunImport();

	/** Imports the plan image as a texture and opens the Wall Correction window for this run. */
	void OpenCorrectionForCurrentSettings(bool bImportImage);

	/** Serialises the current settings for the Python bridge. */
	FString BuildOptionsJson() const;

	void LoadSettings();
	void SaveSettings() const;

	TSharedPtr<SListView<TSharedPtr<FFloorPlanLogLine>>> LogListView;
	TArray<TSharedPtr<FFloorPlanLogLine>> LogLines;

	// Settings mirrored to EditorPerProjectUserSettings.
	FString FloorPlanPath;
	FString CadLayerFilter;
	FString OdaConverterPath;
	float PixelsPerFoot = 50.0f;
	float WallHeightCm = 300.0f;
	float DefaultThicknessCm = 15.0f;
	float DxfUnitsToCm = 2.54f;
	float RasterDpi = 300.0f;
	int32 PdfPageIndex = 0;
	bool bGenerateCollision = true;
	/** One WallGeneratorActor holding every wall (true) or one actor per wall (false). */
	bool bCombinedActor = true;

	FText StatusText;
	bool bIsRunning = false;
};
