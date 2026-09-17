// Copyright Epic Games, Inc. All Rights Reserved.

#include "SFloorPlanCanvas.h"

#include "Engine/Texture2D.h"
#include "Framework/Application/SlateApplication.h"
#include "InputCoreTypes.h"
#include "Rendering/DrawElements.h"
#include "Styling/CoreStyle.h"

namespace FloorPlanCanvas
{
	constexpr float MinZoom = 0.02f;
	constexpr float MaxZoom = 40.0f;
	constexpr float PickRadiusPx = 8.0f;
	constexpr float EndpointSnapPx = 10.0f;
	constexpr float MinWallLengthCm = 10.0f;
	constexpr float EndpointMarkerPx = 6.0f;

	const FLinearColor Background(0.09f, 0.09f, 0.10f);
	const FLinearColor Detected(0.25f, 0.75f, 1.00f);
	const FLinearColor Added(0.35f, 0.90f, 0.40f);
	const FLinearColor Selected(1.00f, 0.60f, 0.10f);
	const FLinearColor Hovered(1.00f, 1.00f, 1.00f);
	const FLinearColor Drawing(1.00f, 0.90f, 0.20f);

	float DistanceToSegment(const FVector2D& P, const FVector2D& A, const FVector2D& B)
	{
		const FVector2D AB = B - A;
		const double LengthSquared = AB.SizeSquared();
		if (LengthSquared <= KINDA_SMALL_NUMBER)
		{
			return static_cast<float>(FVector2D::Distance(P, A));
		}
		const double T = FMath::Clamp(FVector2D::DotProduct(P - A, AB) / LengthSquared, 0.0, 1.0);
		return static_cast<float>(FVector2D::Distance(P, A + AB * T));
	}

	void DrawMarker(FSlateWindowElementList& OutDrawElements, const int32 Layer, const FGeometry& Geometry,
		const FSlateBrush* Brush, const FVector2D& Local, const FLinearColor& Color)
	{
		const float Half = EndpointMarkerPx * 0.5f;
		FSlateDrawElement::MakeBox(
			OutDrawElements,
			Layer,
			Geometry.ToPaintGeometry(FVector2f(EndpointMarkerPx, EndpointMarkerPx), FSlateLayoutTransform(FVector2f(Local - FVector2D(Half, Half)))),
			Brush,
			ESlateDrawEffect::None,
			Color);
	}
}

void SFloorPlanCanvas::Construct(const FArguments& InArgs)
{
	OnWallDrawn = InArgs._OnWallDrawn;
	OnWallPicked = InArgs._OnWallPicked;
	OnDeleteRequested = InArgs._OnDeleteRequested;

	ImageBrush.DrawAs = ESlateBrushDrawType::Image;
	ImageBrush.Tiling = ESlateBrushTileType::NoTile;
}

// ---------------------------------------------------------------- data ----

void SFloorPlanCanvas::SetImage(UTexture2D* InTexture, const float InCmPerPixel)
{
	Texture.Reset(InTexture);
	if (InTexture)
	{
		ImageSizePx = FVector2D(InTexture->GetSizeX(), InTexture->GetSizeY());
		ImageBrush.SetResourceObject(InTexture);
		ImageBrush.ImageSize = ImageSizePx;
	}
	else
	{
		ImageSizePx = FVector2D::ZeroVector;
		ImageBrush.SetResourceObject(nullptr);
	}
	CmPerPixel = FMath::Max(InCmPerPixel, 0.0001f);
	bFitPending = true;
}

void SFloorPlanCanvas::SetScale(const float InCmPerPixel)
{
	CmPerPixel = FMath::Max(InCmPerPixel, 0.0001f);
}

void SFloorPlanCanvas::SetWalls(const TArray<FCanvasWall>& InWalls)
{
	const bool bHadContent = Walls.Num() > 0 || Texture.IsValid();
	Walls = InWalls;
	HoveredWall = INDEX_NONE;
	if (!SelectedId.IsEmpty() && !Walls.ContainsByPredicate([this](const FCanvasWall& W) { return W.Id == SelectedId; }))
	{
		SelectedId.Reset();
	}
	// Only auto-fit when there was nothing to look at before; keep the user's view otherwise.
	if (!bHadContent && !Texture.IsValid())
	{
		bFitPending = true;
	}
}

void SFloorPlanCanvas::SetSelectedWall(const FString& Id)
{
	SelectedId = Id;
}

void SFloorPlanCanvas::SetMode(const EFloorPlanCanvasMode InMode)
{
	Mode = InMode;
	if (Mode != EFloorPlanCanvasMode::Draw)
	{
		bDrawing = false;
	}
}

void SFloorPlanCanvas::SetSnapEnabled(const bool bEnabled)
{
	bSnap = bEnabled;
}

void SFloorPlanCanvas::SetImageOpacity(const float Opacity)
{
	ImageOpacity = FMath::Clamp(Opacity, 0.0f, 1.0f);
}

void SFloorPlanCanvas::FitToContent()
{
	const FVector2D Size = GetCachedGeometry().GetLocalSize();
	if (Size.X > 1.0 && Size.Y > 1.0)
	{
		ApplyFit(Size);
	}
	else
	{
		bFitPending = true;
	}
}

FVector2D SFloorPlanCanvas::GetViewCentreCm() const
{
	return LocalToWorld(GetCachedGeometry().GetLocalSize() * 0.5);
}

// ------------------------------------------------------------- spaces -----

FVector2D SFloorPlanCanvas::WorldToImage(const FVector2D& Cm) const
{
	return FVector2D(Cm.X / CmPerPixel, ImageSizePx.Y - Cm.Y / CmPerPixel);
}

FVector2D SFloorPlanCanvas::ImageToWorld(const FVector2D& Px) const
{
	return FVector2D(Px.X * CmPerPixel, (ImageSizePx.Y - Px.Y) * CmPerPixel);
}

FVector2D SFloorPlanCanvas::ImageToLocal(const FVector2D& Px) const
{
	return Px * Zoom + Pan;
}

FVector2D SFloorPlanCanvas::LocalToImage(const FVector2D& Local) const
{
	return (Local - Pan) / Zoom;
}

bool SFloorPlanCanvas::GetContentBounds(FVector2D& OutMin, FVector2D& OutMax) const
{
	if (Texture.IsValid() && ImageSizePx.X > 0.0)
	{
		OutMin = FVector2D::ZeroVector;
		OutMax = ImageSizePx;
		return true;
	}
	if (Walls.Num() == 0)
	{
		return false;
	}

	OutMin = FVector2D(TNumericLimits<double>::Max(), TNumericLimits<double>::Max());
	OutMax = FVector2D(TNumericLimits<double>::Lowest(), TNumericLimits<double>::Lowest());
	for (const FCanvasWall& Wall : Walls)
	{
		for (const FVector2D& Point : { WorldToImage(Wall.Start), WorldToImage(Wall.End) })
		{
			OutMin = FVector2D::Min(OutMin, Point);
			OutMax = FVector2D::Max(OutMax, Point);
		}
	}
	const FVector2D Margin(50.0, 50.0);
	OutMin -= Margin;
	OutMax += Margin;
	return true;
}

void SFloorPlanCanvas::ApplyFit(const FVector2D& LocalSize) const
{
	bFitPending = false;

	FVector2D Min, Max;
	if (!GetContentBounds(Min, Max))
	{
		Zoom = 1.0f;
		Pan = LocalSize * 0.5;
		return;
	}

	const FVector2D Extent = FVector2D::Max(Max - Min, FVector2D(1.0, 1.0));
	const float Fit = static_cast<float>(FMath::Min(LocalSize.X / Extent.X, LocalSize.Y / Extent.Y)) * 0.92f;
	Zoom = FMath::Clamp(Fit, FloorPlanCanvas::MinZoom, FloorPlanCanvas::MaxZoom);
	Pan = LocalSize * 0.5 - (Min + Max) * 0.5 * Zoom;
}

// -------------------------------------------------------------- picking ---

int32 SFloorPlanCanvas::PickWall(const FVector2D& Local) const
{
	int32 Best = INDEX_NONE;
	float BestDistance = FloorPlanCanvas::PickRadiusPx;
	for (int32 Index = 0; Index < Walls.Num(); ++Index)
	{
		const float Distance = FloorPlanCanvas::DistanceToSegment(
			Local, WorldToLocal(Walls[Index].Start), WorldToLocal(Walls[Index].End));
		if (Distance < BestDistance)
		{
			BestDistance = Distance;
			Best = Index;
		}
	}
	return Best;
}

FVector2D SFloorPlanCanvas::SnapEndpoint(const FVector2D& Cm, const FVector2D* Anchor) const
{
	if (!bSnap)
	{
		return Cm;
	}

	// Join onto an existing wall end when the cursor is close to one.
	const FVector2D Local = WorldToLocal(Cm);
	float Best = FloorPlanCanvas::EndpointSnapPx;
	const FVector2D* BestPoint = nullptr;
	for (const FCanvasWall& Wall : Walls)
	{
		for (const FVector2D* Point : { &Wall.Start, &Wall.End })
		{
			const float Distance = static_cast<float>(FVector2D::Distance(WorldToLocal(*Point), Local));
			if (Distance < Best)
			{
				Best = Distance;
				BestPoint = Point;
			}
		}
	}
	if (BestPoint)
	{
		return *BestPoint;
	}

	// Otherwise keep the wall horizontal or vertical relative to where the drag started.
	if (Anchor)
	{
		const FVector2D Delta = Cm - *Anchor;
		return FMath::Abs(Delta.X) >= FMath::Abs(Delta.Y)
			? FVector2D(Cm.X, Anchor->Y)
			: FVector2D(Anchor->X, Cm.Y);
	}
	return Cm;
}

// ---------------------------------------------------------------- paint ---

int32 SFloorPlanCanvas::OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
	FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const
{
	const FVector2D LocalSize = AllottedGeometry.GetLocalSize();
	if (bFitPending && LocalSize.X > 1.0 && LocalSize.Y > 1.0)
	{
		ApplyFit(LocalSize);
	}

	const FSlateBrush* White = FCoreStyle::Get().GetBrush("WhiteBrush");

	FSlateDrawElement::MakeBox(
		OutDrawElements, LayerId, AllottedGeometry.ToPaintGeometry(), White, ESlateDrawEffect::None, FloorPlanCanvas::Background);
	int32 Layer = LayerId + 1;

	if (Texture.IsValid() && ImageSizePx.X > 0.0)
	{
		FSlateDrawElement::MakeBox(
			OutDrawElements,
			Layer,
			AllottedGeometry.ToPaintGeometry(FVector2f(ImageSizePx * Zoom), FSlateLayoutTransform(FVector2f(Pan))),
			&ImageBrush,
			ESlateDrawEffect::None,
			FLinearColor(1.0f, 1.0f, 1.0f, ImageOpacity));
	}
	++Layer;

	const int32 WallLayer = Layer;
	const int32 HighlightLayer = Layer + 1;
	const int32 MarkerLayer = Layer + 2;

	for (int32 Index = 0; Index < Walls.Num(); ++Index)
	{
		const FCanvasWall& Wall = Walls[Index];
		const bool bSelected = !SelectedId.IsEmpty() && Wall.Id == SelectedId;
		const bool bHovered = Index == HoveredWall && Mode == EFloorPlanCanvasMode::Select;

		const FVector2D A = WorldToLocal(Wall.Start);
		const FVector2D B = WorldToLocal(Wall.End);
		const float Thickness = FMath::Clamp(Wall.Thickness / CmPerPixel * Zoom, 1.5f, 40.0f);

		FLinearColor Color = Wall.Origin == TEXT("added") ? FloorPlanCanvas::Added : FloorPlanCanvas::Detected;
		Color.A = 0.85f;
		if (bSelected)
		{
			Color = FloorPlanCanvas::Selected;
		}
		else if (bHovered)
		{
			Color = FloorPlanCanvas::Hovered;
		}

		const TArray<FVector2f> Points = { FVector2f(A), FVector2f(B) };
		FSlateDrawElement::MakeLines(
			OutDrawElements, bSelected || bHovered ? HighlightLayer : WallLayer,
			AllottedGeometry.ToPaintGeometry(), Points, ESlateDrawEffect::None, Color, /*bAntialias*/ true, Thickness);

		if (bSelected)
		{
			FloorPlanCanvas::DrawMarker(OutDrawElements, MarkerLayer, AllottedGeometry, White, A, FloorPlanCanvas::Selected);
			FloorPlanCanvas::DrawMarker(OutDrawElements, MarkerLayer, AllottedGeometry, White, B, FloorPlanCanvas::Selected);
		}
	}

	if (bDrawing)
	{
		const FVector2D A = WorldToLocal(DragStartCm);
		const FVector2D B = WorldToLocal(DragCurrentCm);
		const TArray<FVector2f> Points = { FVector2f(A), FVector2f(B) };
		FSlateDrawElement::MakeLines(
			OutDrawElements, HighlightLayer, AllottedGeometry.ToPaintGeometry(), Points, ESlateDrawEffect::None,
			FloorPlanCanvas::Drawing, /*bAntialias*/ true, 2.5f);
		FloorPlanCanvas::DrawMarker(OutDrawElements, MarkerLayer, AllottedGeometry, White, A, FloorPlanCanvas::Drawing);
		FloorPlanCanvas::DrawMarker(OutDrawElements, MarkerLayer, AllottedGeometry, White, B, FloorPlanCanvas::Drawing);
	}

	return MarkerLayer + 1;
}

FVector2D SFloorPlanCanvas::ComputeDesiredSize(float) const
{
	return FVector2D(480.0, 320.0);
}

// ---------------------------------------------------------------- input ---

FReply SFloorPlanCanvas::OnMouseButtonDown(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	const FVector2D Local = MyGeometry.AbsoluteToLocal(MouseEvent.GetScreenSpacePosition());
	const FKey Button = MouseEvent.GetEffectingButton();

	if (Button == EKeys::LeftMouseButton)
	{
		if (Mode == EFloorPlanCanvasMode::Draw)
		{
			bDrawing = true;
			DragStartCm = SnapEndpoint(LocalToWorld(Local), nullptr);
			DragCurrentCm = DragStartCm;
			return FReply::Handled().CaptureMouse(SharedThis(this)).SetUserFocus(SharedThis(this), EFocusCause::Mouse);
		}

		const int32 Hit = PickWall(Local);
		SelectedId = Hit != INDEX_NONE ? Walls[Hit].Id : FString();
		OnWallPicked.ExecuteIfBound(SelectedId);
		return FReply::Handled().SetUserFocus(SharedThis(this), EFocusCause::Mouse);
	}

	if (Button == EKeys::RightMouseButton || Button == EKeys::MiddleMouseButton)
	{
		bPanning = true;
		PanLastLocal = Local;
		return FReply::Handled().CaptureMouse(SharedThis(this));
	}

	return FReply::Unhandled();
}

FReply SFloorPlanCanvas::OnMouseMove(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	const FVector2D Local = MyGeometry.AbsoluteToLocal(MouseEvent.GetScreenSpacePosition());

	if (bPanning)
	{
		Pan += Local - PanLastLocal;
		PanLastLocal = Local;
		bFitPending = false;
		return FReply::Handled();
	}

	if (bDrawing)
	{
		DragCurrentCm = SnapEndpoint(LocalToWorld(Local), &DragStartCm);
		return FReply::Handled();
	}

	HoveredWall = Mode == EFloorPlanCanvasMode::Select ? PickWall(Local) : INDEX_NONE;
	return FReply::Unhandled();
}

FReply SFloorPlanCanvas::OnMouseButtonUp(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	const FKey Button = MouseEvent.GetEffectingButton();

	if (Button == EKeys::LeftMouseButton && bDrawing)
	{
		bDrawing = false;
		const FVector2D End = SnapEndpoint(LocalToWorld(MyGeometry.AbsoluteToLocal(MouseEvent.GetScreenSpacePosition())), &DragStartCm);
		if (FVector2D::Distance(DragStartCm, End) >= FloorPlanCanvas::MinWallLengthCm)
		{
			OnWallDrawn.ExecuteIfBound(DragStartCm, End);
		}
		return FReply::Handled().ReleaseMouseCapture();
	}

	if ((Button == EKeys::RightMouseButton || Button == EKeys::MiddleMouseButton) && bPanning)
	{
		bPanning = false;
		return FReply::Handled().ReleaseMouseCapture();
	}

	return FReply::Unhandled();
}

FReply SFloorPlanCanvas::OnMouseWheel(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	const FVector2D Local = MyGeometry.AbsoluteToLocal(MouseEvent.GetScreenSpacePosition());
	const float NewZoom = FMath::Clamp(
		Zoom * FMath::Pow(1.15f, MouseEvent.GetWheelDelta()), FloorPlanCanvas::MinZoom, FloorPlanCanvas::MaxZoom);
	// Keep the point under the cursor fixed while zooming.
	Pan = Local - (Local - Pan) * (NewZoom / Zoom);
	Zoom = NewZoom;
	bFitPending = false;
	return FReply::Handled();
}

FReply SFloorPlanCanvas::OnKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent)
{
	const FKey Key = InKeyEvent.GetKey();
	if (Key == EKeys::Delete || Key == EKeys::BackSpace)
	{
		if (!SelectedId.IsEmpty())
		{
			OnDeleteRequested.ExecuteIfBound();
		}
		return FReply::Handled();
	}
	if (Key == EKeys::Escape)
	{
		if (bDrawing)
		{
			bDrawing = false;
			return FReply::Handled().ReleaseMouseCapture();
		}
		SelectedId.Reset();
		OnWallPicked.ExecuteIfBound(SelectedId);
		return FReply::Handled();
	}
	if (Key == EKeys::F)
	{
		FitToContent();
		return FReply::Handled();
	}
	return FReply::Unhandled();
}

FCursorReply SFloorPlanCanvas::OnCursorQuery(const FGeometry& MyGeometry, const FPointerEvent& CursorEvent) const
{
	if (bPanning)
	{
		return FCursorReply::Cursor(EMouseCursor::GrabHandClosed);
	}
	if (Mode == EFloorPlanCanvasMode::Draw)
	{
		return FCursorReply::Cursor(EMouseCursor::Crosshairs);
	}
	return FCursorReply::Cursor(HoveredWall != INDEX_NONE ? EMouseCursor::Hand : EMouseCursor::Default);
}
