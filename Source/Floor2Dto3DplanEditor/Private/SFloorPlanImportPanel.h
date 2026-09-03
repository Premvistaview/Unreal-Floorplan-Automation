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
 * Dockable panel that drives the floor-plan-to-walls pipeline.
 *
 * Detection and actor spawning stay in Python; this panel collects the
 * settings, runs the bridge module, and mirrors the Python log locally so the
 * user never has to dig through the Output Log.
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
	FReply OnClearLogClicked();
	FReply OnCopyLogClicked();

	bool CanGenerate() const;

	/** Appends text to the log, splitting embedded newlines into separate rows. */
	void AppendLog(const FString& Text, EFloorPlanLogSeverity Severity);

	/** Runs the Python bridge and mirrors its captured output into the log. */
	void RunImport();

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

	FText StatusText;
	bool bIsRunning = false;
};
