// Copyright Epic Games, Inc. All Rights Reserved.
#pragma once

#include "CoreMinimal.h"
#include "Styling/SlateBrush.h"
#include "UObject/StrongObjectPtr.h"
#include "Widgets/SLeafWidget.h"

class UTexture2D;

/** One wall as the canvas draws it. Start/End are world-space centimetres. */
struct FCanvasWall
{
	FString Id;
	FString Label;
	FString Origin;
	FVector2D Start = FVector2D::ZeroVector;
	FVector2D End = FVector2D::ZeroVector;
	float Thickness = 15.0f;
};

enum class EFloorPlanCanvasMode : uint8
{
	/** Click a wall to select it. */
	Select,
	/** Drag to add a wall. */
	Draw
};

DECLARE_DELEGATE_TwoParams(FOnCanvasWallDrawn, FVector2D /*StartCm*/, FVector2D /*EndCm*/);
DECLARE_DELEGATE_OneParam(FOnCanvasWallPicked, const FString& /*Id, empty when nothing was hit*/);

/**
 * 2D view of the floor plan: the imported source image (when there is one)
 * with every staged wall centreline drawn over it at true scale.
 *
 * World cm <-> image px follows the detector's convention: X = px.x * cm/px,
 * Y = (image height - px.y) * cm/px, so world Y grows upward on the drawing.
 *
 * Interaction: left-drag draws a wall (Draw mode) or picks one (Select mode);
 * right/middle-drag pans; wheel zooms about the cursor; Delete/Backspace
 * asks the owner to remove the selection; Escape cancels a drag.
 */
class SFloorPlanCanvas : public SLeafWidget
{
public:
	SLATE_BEGIN_ARGS(SFloorPlanCanvas) {}
		SLATE_EVENT(FOnCanvasWallDrawn, OnWallDrawn)
		SLATE_EVENT(FOnCanvasWallPicked, OnWallPicked)
		SLATE_EVENT(FSimpleDelegate, OnDeleteRequested)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

	/** Replace the background. Pass nullptr for sources with no raster (PDF vectors, DXF). */
	void SetImage(UTexture2D* Texture, float InCmPerPixel);
	void SetScale(float InCmPerPixel);
	void SetWalls(const TArray<FCanvasWall>& InWalls);
	void SetSelectedWall(const FString& Id);
	void SetMode(EFloorPlanCanvasMode InMode);
	void SetSnapEnabled(bool bEnabled);
	void SetImageOpacity(float Opacity);

	/** Zoom and pan so the image (or all walls) fills the widget. */
	void FitToContent();

	EFloorPlanCanvasMode GetMode() const { return Mode; }
	bool IsSnapEnabled() const { return bSnap; }
	float GetZoom() const { return Zoom; }
	bool HasImage() const { return Texture.IsValid(); }
	/** World cm at the centre of the current view, for "Add Wall" from the toolbar. */
	FVector2D GetViewCentreCm() const;

	// SWidget
	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
		FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle,
		bool bParentEnabled) const override;
	virtual FVector2D ComputeDesiredSize(float) const override;
	virtual FReply OnMouseButtonDown(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) override;
	virtual FReply OnMouseButtonUp(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) override;
	virtual FReply OnMouseMove(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) override;
	virtual FReply OnMouseWheel(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) override;
	virtual FReply OnKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent) override;
	virtual FCursorReply OnCursorQuery(const FGeometry& MyGeometry, const FPointerEvent& CursorEvent) const override;
	virtual bool SupportsKeyboardFocus() const override { return true; }

private:
	// Coordinate spaces: world cm  <->  image px  <->  widget-local px.
	FVector2D WorldToImage(const FVector2D& Cm) const;
	FVector2D ImageToWorld(const FVector2D& Px) const;
	FVector2D ImageToLocal(const FVector2D& Px) const;
	FVector2D LocalToImage(const FVector2D& Local) const;
	FVector2D WorldToLocal(const FVector2D& Cm) const { return ImageToLocal(WorldToImage(Cm)); }
	FVector2D LocalToWorld(const FVector2D& Local) const { return ImageToWorld(LocalToImage(Local)); }

	/** Bounds of the drawable content in image px. */
	bool GetContentBounds(FVector2D& OutMin, FVector2D& OutMax) const;
	void ApplyFit(const FVector2D& LocalSize) const;

	/** Nearest wall to a local point within the pick radius, or INDEX_NONE. */
	int32 PickWall(const FVector2D& Local) const;

	/** Applies axis and endpoint snapping to a drag endpoint (world cm). */
	FVector2D SnapEndpoint(const FVector2D& Cm, const FVector2D* Anchor) const;

	FOnCanvasWallDrawn OnWallDrawn;
	FOnCanvasWallPicked OnWallPicked;
	FSimpleDelegate OnDeleteRequested;

	TStrongObjectPtr<UTexture2D> Texture;
	FSlateBrush ImageBrush;
	FVector2D ImageSizePx = FVector2D::ZeroVector;
	float CmPerPixel = 1.0f;
	float ImageOpacity = 0.85f;

	TArray<FCanvasWall> Walls;
	FString SelectedId;
	EFloorPlanCanvasMode Mode = EFloorPlanCanvasMode::Select;
	bool bSnap = true;

	// View. Mutable so a deferred fit can be applied during the first paint.
	mutable float Zoom = 1.0f;
	mutable FVector2D Pan = FVector2D::ZeroVector;
	mutable bool bFitPending = true;

	// Interaction.
	bool bDrawing = false;
	bool bPanning = false;
	FVector2D DragStartCm = FVector2D::ZeroVector;
	FVector2D DragCurrentCm = FVector2D::ZeroVector;
	FVector2D PanLastLocal = FVector2D::ZeroVector;
	int32 HoveredWall = INDEX_NONE;
};
