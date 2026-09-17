// Copyright Epic Games, Inc. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Floor2Dto3DplanEditorModule.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/Views/SListView.h"

class SFloorPlanCanvas;
class UTexture2D;

/** One staged wall, as reported by the Python bridge's list_walls(). */
struct FFloorPlanWallItem
{
	/** WallSegments index (combined mode) or actor path (individual mode). */
	FString Id;
	FString Label;
	/** "detected" or "added". */
	FString Origin;
	/** 1-based index into the raw detection, or INDEX_NONE for added walls. */
	int32 Index = INDEX_NONE;
	FString Summary;
	/** World-space centreline in centimetres. */
	FVector2D Start = FVector2D::ZeroVector;
	FVector2D End = FVector2D::ZeroVector;
	float Thickness = 15.0f;
};

/**
 * The Wall Correction window: the imported floor-plan image with every staged
 * wall drawn over it, a list of those walls, and the tools to fix detection
 * mistakes by hand — draw a missed wall, remove a false positive, then
 * Finalize. Every edit goes straight to the single FloorPlan_Walls actor
 * through the Python bridge; nothing is re-detected.
 */
class SWallCorrectionPanel : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SWallCorrectionPanel) {}
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

	/** Point the window at a detection run: loads its image and refreshes the walls. */
	void SetContext(const FWallCorrectionContext& InContext);

	/** Re-read the staged walls from the level. */
	void RefreshWalls();

private:
	TSharedRef<SWidget> BuildToolbar();
	TSharedRef<SWidget> BuildSidebar();
	TSharedRef<ITableRow> OnGenerateWallRow(TSharedPtr<FFloorPlanWallItem> Item, const TSharedRef<STableViewBase>& OwnerTable);
	void OnListSelectionChanged(TSharedPtr<FFloorPlanWallItem> Item, ESelectInfo::Type SelectInfo);

	// Canvas callbacks.
	void HandleWallDrawn(FVector2D StartCm, FVector2D EndCm);
	void HandleWallPicked(const FString& Id);
	void HandleDeleteRequested();

	// Toolbar / row actions.
	FReply OnAddWallClicked();
	FReply OnRemoveSelectedClicked();
	FReply OnRefreshClicked();
	FReply OnFitClicked();
	FReply OnFinalizeClicked();
	FReply OnSelectInViewportClicked(TSharedPtr<FFloorPlanWallItem> Item);
	FReply OnRemoveRowClicked(TSharedPtr<FFloorPlanWallItem> Item);

	/** Adds a wall between two world points through Python and selects it. */
	void AddWall(const FVector2D& StartCm, const FVector2D& EndCm);
	/** Removes one wall through Python and refreshes. */
	void RemoveWall(const FString& Id, const FString& Label);
	/** Keeps the canvas and the list agreeing on the selection. */
	void SelectWall(const FString& Id);

	/** Runs Python, mirrors its log to the Output Log, and surfaces errors in the status line. */
	bool RunPython(const FString& Command, bool bShowProgress, const FText& ProgressText, FString& OutResult);

	void LoadTexture();
	bool CanEdit() const { return !bIsRunning; }
	FString ThicknessHeightCollisionArgs() const;

	FWallCorrectionContext Context;

	TSharedPtr<SFloorPlanCanvas> Canvas;
	TSharedPtr<SListView<TSharedPtr<FFloorPlanWallItem>>> WallListView;
	TArray<TSharedPtr<FFloorPlanWallItem>> WallItems;

	FString SelectedId;
	FText SummaryText;
	FText StatusText;
	bool bIsRunning = false;
	/** Set while we push a selection into the list so its callback does not echo it back. */
	bool bSyncingSelection = false;
};
