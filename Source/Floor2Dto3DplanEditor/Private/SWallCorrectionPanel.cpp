// Copyright Epic Games, Inc. All Rights Reserved.

#include "SWallCorrectionPanel.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/Texture2D.h"
#include "FloorPlanPythonBridge.h"
#include "ImageUtils.h"
#include "Misc/Paths.h"
#include "SFloorPlanCanvas.h"
#include "Styling/AppStyle.h"
#include "Styling/CoreStyle.h"
#include "UObject/SoftObjectPath.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SSeparator.h"
#include "Widgets/Layout/SSplitter.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Views/STableRow.h"

DEFINE_LOG_CATEGORY_STATIC(LogFloorPlanCorrection, Log, All);

#define LOCTEXT_NAMESPACE "SWallCorrectionPanel"

namespace WallCorrectionPanel
{
	constexpr float ToolbarWallLengthCm = 200.0f;

	TSharedRef<SWidget> ModeToggle(const FText& Label, const FText& Tooltip, TAttribute<ECheckBoxState> IsChecked,
		FOnCheckStateChanged OnChanged)
	{
		return SNew(SCheckBox)
			.Style(FAppStyle::Get(), "ToggleButtonCheckbox")
			.ToolTipText(Tooltip)
			.IsChecked(IsChecked)
			.OnCheckStateChanged(OnChanged)
			[
				SNew(STextBlock)
				.Text(Label)
				.Margin(FMargin(8.0f, 2.0f))
			];
	}

	bool ReadVector2D(const TSharedPtr<FJsonObject>& Row, const TCHAR* Field, FVector2D& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Row->TryGetArrayField(Field, Values) || !Values || Values->Num() < 2)
		{
			return false;
		}
		Out.X = (*Values)[0]->AsNumber();
		Out.Y = (*Values)[1]->AsNumber();
		return true;
	}
}

void SWallCorrectionPanel::Construct(const FArguments& InArgs)
{
	SummaryText = LOCTEXT("SummaryEmpty", "No walls staged. Run Detect Editable Walls in the Floor Plan Import panel, or draw walls here.");
	StatusText = LOCTEXT("StatusIdle", "Draw: drag to add a wall. Select: click a wall, then Delete. Right-drag pans, wheel zooms, F fits.");

	ChildSlot
	[
		SNew(SBorder)
		.BorderImage(FAppStyle::Get().GetBrush("ToolPanel.GroupBorder"))
		.Padding(6.0f)
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot()
			.AutoHeight()
			[
				BuildToolbar()
			]
			+ SVerticalBox::Slot()
			.FillHeight(1.0f)
			.Padding(0.0f, 6.0f, 0.0f, 0.0f)
			[
				SNew(SSplitter)
				.Orientation(Orient_Horizontal)
				+ SSplitter::Slot()
				.Value(0.7f)
				[
					SNew(SBorder)
					.BorderImage(FAppStyle::Get().GetBrush("Brushes.Recessed"))
					.Padding(1.0f)
					[
						SAssignNew(Canvas, SFloorPlanCanvas)
						.OnWallDrawn(this, &SWallCorrectionPanel::HandleWallDrawn)
						.OnWallPicked(this, &SWallCorrectionPanel::HandleWallPicked)
						.OnDeleteRequested(this, &SWallCorrectionPanel::HandleDeleteRequested)
					]
				]
				+ SSplitter::Slot()
				.Value(0.3f)
				[
					SNew(SBox)
					.Padding(FMargin(6.0f, 0.0f, 0.0f, 0.0f))
					[
						BuildSidebar()
					]
				]
			]
			+ SVerticalBox::Slot()
			.AutoHeight()
			.Padding(0.0f, 6.0f, 0.0f, 0.0f)
			[
				SNew(STextBlock)
				.Text_Lambda([this]() { return StatusText; })
				.AutoWrapText(true)
				.ColorAndOpacity(FSlateColor::UseSubduedForeground())
			]
		]
	];
}

TSharedRef<SWidget> SWallCorrectionPanel::BuildToolbar()
{
	return SNew(SHorizontalBox)
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.VAlign(VAlign_Center)
		[
			WallCorrectionPanel::ModeToggle(
				LOCTEXT("ModeSelect", "Select"),
				LOCTEXT("ModeSelectTooltip", "Click a wall on the plan to select it. Delete removes it."),
				TAttribute<ECheckBoxState>::CreateLambda([this]()
				{
					return Canvas.IsValid() && Canvas->GetMode() == EFloorPlanCanvasMode::Select
						? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
				}),
				FOnCheckStateChanged::CreateLambda([this](ECheckBoxState State)
				{
					if (State == ECheckBoxState::Checked && Canvas.IsValid())
					{
						Canvas->SetMode(EFloorPlanCanvasMode::Select);
					}
				}))
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.VAlign(VAlign_Center)
		.Padding(2.0f, 0.0f, 0.0f, 0.0f)
		[
			WallCorrectionPanel::ModeToggle(
				LOCTEXT("ModeDraw", "Draw"),
				LOCTEXT("ModeDrawTooltip", "Drag on the plan to add a wall the detector missed. Snaps to horizontal/vertical and to existing wall ends."),
				TAttribute<ECheckBoxState>::CreateLambda([this]()
				{
					return Canvas.IsValid() && Canvas->GetMode() == EFloorPlanCanvasMode::Draw
						? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
				}),
				FOnCheckStateChanged::CreateLambda([this](ECheckBoxState State)
				{
					if (State == ECheckBoxState::Checked && Canvas.IsValid())
					{
						Canvas->SetMode(EFloorPlanCanvasMode::Draw);
					}
				}))
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.VAlign(VAlign_Center)
		.Padding(12.0f, 0.0f, 0.0f, 0.0f)
		[
			SNew(SCheckBox)
			.ToolTipText(LOCTEXT("SnapTooltip", "Keep drawn walls horizontal or vertical and join them onto nearby wall ends."))
			.IsChecked_Lambda([this]()
			{
				return Canvas.IsValid() && Canvas->IsSnapEnabled() ? ECheckBoxState::Checked : ECheckBoxState::Unchecked;
			})
			.OnCheckStateChanged_Lambda([this](ECheckBoxState State)
			{
				if (Canvas.IsValid())
				{
					Canvas->SetSnapEnabled(State == ECheckBoxState::Checked);
				}
			})
			[
				SNew(STextBlock).Text(LOCTEXT("Snap", "Snap"))
			]
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.VAlign(VAlign_Center)
		.Padding(8.0f, 0.0f, 0.0f, 0.0f)
		[
			SNew(SButton)
			.Text(LOCTEXT("Fit", "Fit"))
			.ToolTipText(LOCTEXT("FitTooltip", "Zoom to show the whole plan (F)."))
			.OnClicked(this, &SWallCorrectionPanel::OnFitClicked)
		]
		+ SHorizontalBox::Slot()
		.FillWidth(1.0f)
		.VAlign(VAlign_Center)
		.Padding(12.0f, 0.0f, 0.0f, 0.0f)
		[
			SNew(STextBlock)
			.Text_Lambda([this]() { return SummaryText; })
			.AutoWrapText(true)
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(6.0f, 0.0f, 0.0f, 0.0f)
		[
			SNew(SButton)
			.Text(LOCTEXT("AddWall", "Add Wall"))
			.ToolTipText(LOCTEXT("AddWallTooltip", "Add a 2 m wall in the middle of the view. Or switch to Draw and drag it exactly where it belongs."))
			.IsEnabled_Lambda([this]() { return CanEdit(); })
			.OnClicked(this, &SWallCorrectionPanel::OnAddWallClicked)
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(6.0f, 0.0f, 0.0f, 0.0f)
		[
			SNew(SButton)
			.Text(LOCTEXT("RemoveSelected", "Remove Selected"))
			.ToolTipText(LOCTEXT("RemoveSelectedTooltip", "Delete the selected wall (Delete key does the same)."))
			.IsEnabled_Lambda([this]() { return CanEdit() && !SelectedId.IsEmpty(); })
			.OnClicked(this, &SWallCorrectionPanel::OnRemoveSelectedClicked)
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(6.0f, 0.0f, 0.0f, 0.0f)
		[
			SNew(SButton)
			.Text(LOCTEXT("Refresh", "Refresh"))
			.ToolTipText(LOCTEXT("RefreshTooltip", "Re-read the staged walls after editing the FloorPlan_Walls actor in Details or the viewport."))
			.IsEnabled_Lambda([this]() { return CanEdit(); })
			.OnClicked(this, &SWallCorrectionPanel::OnRefreshClicked)
		]
		+ SHorizontalBox::Slot()
		.AutoWidth()
		.Padding(6.0f, 0.0f, 0.0f, 0.0f)
		[
			SNew(SButton)
			.ButtonStyle(FAppStyle::Get(), "PrimaryButton")
			.Text(LOCTEXT("Finalize", "Finalize"))
			.ToolTipText(LOCTEXT("FinalizeTooltip", "Lock the corrections in: write Saved/FloorPlan/walls_corrected.json, then bake every wall into one Static Mesh asset under /Game/FloorPlan/Meshes (lightmap UVs + simple collision) and replace the Dynamic Mesh actor(s) with a Static Mesh Actor. One-directional: re-detect to edit again."))
			.IsEnabled_Lambda([this]() { return CanEdit() && WallItems.Num() > 0; })
			.OnClicked(this, &SWallCorrectionPanel::OnFinalizeClicked)
		];
}

TSharedRef<SWidget> SWallCorrectionPanel::BuildSidebar()
{
	return SNew(SVerticalBox)
		+ SVerticalBox::Slot()
		.AutoHeight()
		[
			SNew(STextBlock)
			.Text(LOCTEXT("WallsHeader", "Walls"))
			.Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
		]
		+ SVerticalBox::Slot()
		.AutoHeight()
		.Padding(0.0f, 2.0f, 0.0f, 4.0f)
		[
			SNew(STextBlock)
			.Text(LOCTEXT("WallsHint", "Blue = detected, green = added. Click a row to highlight it on the plan."))
			.ColorAndOpacity(FSlateColor::UseSubduedForeground())
			.AutoWrapText(true)
		]
		+ SVerticalBox::Slot()
		.FillHeight(1.0f)
		[
			SNew(SBorder)
			.BorderImage(FAppStyle::Get().GetBrush("Brushes.Recessed"))
			.Padding(3.0f)
			[
				SAssignNew(WallListView, SListView<TSharedPtr<FFloorPlanWallItem>>)
				.ListItemsSource(&WallItems)
				.SelectionMode(ESelectionMode::Single)
				.OnGenerateRow(this, &SWallCorrectionPanel::OnGenerateWallRow)
				.OnSelectionChanged(this, &SWallCorrectionPanel::OnListSelectionChanged)
			]
		];
}

TSharedRef<ITableRow> SWallCorrectionPanel::OnGenerateWallRow(
	TSharedPtr<FFloorPlanWallItem> Item, const TSharedRef<STableViewBase>& OwnerTable)
{
	const bool bAdded = Item.IsValid() && Item->Origin == TEXT("added");
	const FSlateColor Swatch = bAdded
		? FSlateColor(FLinearColor(0.35f, 0.90f, 0.40f))
		: FSlateColor(FLinearColor(0.25f, 0.75f, 1.00f));

	return SNew(STableRow<TSharedPtr<FFloorPlanWallItem>>, OwnerTable)
		.Padding(FMargin(2.0f, 3.0f))
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.VAlign(VAlign_Center)
			.Padding(0.0f, 0.0f, 6.0f, 0.0f)
			[
				SNew(SBox)
				.WidthOverride(8.0f)
				.HeightOverride(8.0f)
				[
					SNew(SBorder)
					.BorderImage(FCoreStyle::Get().GetBrush("WhiteBrush"))
					.BorderBackgroundColor(Swatch)
				]
			]
			+ SHorizontalBox::Slot()
			.FillWidth(1.0f)
			.VAlign(VAlign_Center)
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot()
				.AutoHeight()
				[
					SNew(STextBlock)
					.Text(FText::FromString(Item.IsValid() ? Item->Label : FString()))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 9))
				]
				+ SVerticalBox::Slot()
				.AutoHeight()
				[
					SNew(STextBlock)
					.Text(FText::FromString(Item.IsValid() ? Item->Summary : FString()))
					.Font(FCoreStyle::GetDefaultFontStyle("Mono", 8))
					.ColorAndOpacity(FSlateColor::UseSubduedForeground())
				]
			]
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.VAlign(VAlign_Center)
			.Padding(4.0f, 0.0f, 0.0f, 0.0f)
			[
				SNew(SButton)
				.Text(LOCTEXT("Viewport", "3D"))
				.ToolTipText(LOCTEXT("ViewportTooltip", "Select the wall actor and frame this wall in the level viewport."))
				.IsEnabled_Lambda([this]() { return CanEdit(); })
				.OnClicked_Lambda([this, Item]() { return OnSelectInViewportClicked(Item); })
			]
			+ SHorizontalBox::Slot()
			.AutoWidth()
			.VAlign(VAlign_Center)
			.Padding(4.0f, 0.0f, 0.0f, 0.0f)
			[
				SNew(SButton)
				.Text(LOCTEXT("Remove", "Remove"))
				.ToolTipText(LOCTEXT("RemoveTooltip", "Delete this wall. Use it for false positives such as furniture, text, or door arcs."))
				.IsEnabled_Lambda([this]() { return CanEdit(); })
				.OnClicked_Lambda([this, Item]() { return OnRemoveRowClicked(Item); })
			]
		];
}

// ------------------------------------------------------------- context ----

void SWallCorrectionPanel::SetContext(const FWallCorrectionContext& InContext)
{
	Context = InContext;
	LoadTexture();
	RefreshWalls();
	if (Canvas.IsValid())
	{
		Canvas->FitToContent();
	}
}

void SWallCorrectionPanel::LoadTexture()
{
	if (!Canvas.IsValid())
	{
		return;
	}

	UTexture2D* Texture = nullptr;
	if (!Context.TextureAssetPath.IsEmpty())
	{
		// Python reports the package path; the object path needs "Package.Name".
		FString ObjectPath = Context.TextureAssetPath;
		if (!ObjectPath.Contains(TEXT(".")))
		{
			ObjectPath += TEXT(".") + FPaths::GetBaseFilename(ObjectPath);
		}
		Texture = Cast<UTexture2D>(FSoftObjectPath(ObjectPath).TryLoad());
		if (!Texture)
		{
			UE_LOG(LogFloorPlanCorrection, Warning, TEXT("Could not load %s; falling back to the file on disk."), *ObjectPath);
		}
	}

	if (!Texture && Context.HasSource())
	{
		const FString Extension = FPaths::GetExtension(Context.SourcePath).ToLower();
		if ((Extension == TEXT("png") || Extension == TEXT("jpg") || Extension == TEXT("jpeg")) && FPaths::FileExists(Context.SourcePath))
		{
			Texture = FImageUtils::ImportFileAsTexture2D(Context.SourcePath);
		}
	}

	Canvas->SetImage(Texture, Context.CmPerPixel());
	if (!Texture && Context.HasSource())
	{
		StatusText = FText::Format(
			LOCTEXT("StatusNoImage", "No raster image for {0}; showing wall lines only. Draw and remove still work."),
			FText::FromString(FPaths::GetCleanFilename(Context.SourcePath)));
	}
}

void SWallCorrectionPanel::RefreshWalls()
{
	WallItems.Reset();
	TArray<FCanvasWall> CanvasWalls;

	FString Result;
	TSharedPtr<FJsonValue> Payload;
	const TArray<TSharedPtr<FJsonValue>>* Rows = nullptr;
	int32 Detected = 0;
	int32 Added = 0;

	if (RunPython(TEXT("__import__('floorplan_panel').list_walls_payload()"), false, FText::GetEmpty(), Result)
		&& FloorPlanPython::DecodePayload(Result, Payload)
		&& Payload->TryGetArray(Rows)
		&& Rows)
	{
		for (const TSharedPtr<FJsonValue>& RowValue : *Rows)
		{
			const TSharedPtr<FJsonObject>* Row = nullptr;
			if (!RowValue.IsValid() || !RowValue->TryGetObject(Row) || !Row)
			{
				continue;
			}

			const TSharedPtr<FFloorPlanWallItem> Item = MakeShared<FFloorPlanWallItem>();
			Item->Id = (*Row)->GetStringField(TEXT("id"));
			Item->Label = (*Row)->GetStringField(TEXT("label"));
			Item->Origin = (*Row)->GetStringField(TEXT("origin"));
			Item->Summary = (*Row)->GetStringField(TEXT("summary"));
			double Number = 0.0;
			Item->Index = (*Row)->TryGetNumberField(TEXT("index"), Number) ? static_cast<int32>(Number) : INDEX_NONE;
			Item->Thickness = (*Row)->TryGetNumberField(TEXT("thickness"), Number) ? static_cast<float>(Number) : 15.0f;
			WallCorrectionPanel::ReadVector2D(*Row, TEXT("start"), Item->Start);
			WallCorrectionPanel::ReadVector2D(*Row, TEXT("end"), Item->End);
			WallItems.Add(Item);

			FCanvasWall& Wall = CanvasWalls.AddDefaulted_GetRef();
			Wall.Id = Item->Id;
			Wall.Label = Item->Label;
			Wall.Origin = Item->Origin;
			Wall.Start = Item->Start;
			Wall.End = Item->End;
			Wall.Thickness = Item->Thickness;

			(Item->Origin == TEXT("added") ? Added : Detected)++;
		}
	}

	if (WallItems.Num() == 0)
	{
		SummaryText = LOCTEXT("SummaryEmpty", "No walls staged. Run Detect Editable Walls in the Floor Plan Import panel, or draw walls here.");
	}
	else if (Added > 0)
	{
		SummaryText = FText::Format(
			LOCTEXT("SummaryMixed", "{0} walls ({1} detected, {2} added) in the FloorPlan_Walls actor"),
			FText::AsNumber(WallItems.Num()), FText::AsNumber(Detected), FText::AsNumber(Added));
	}
	else
	{
		SummaryText = FText::Format(
			LOCTEXT("SummaryDetected", "{0} walls detected in the FloorPlan_Walls actor"),
			FText::AsNumber(WallItems.Num()));
	}

	if (!SelectedId.IsEmpty()
		&& !WallItems.ContainsByPredicate([this](const TSharedPtr<FFloorPlanWallItem>& W) { return W->Id == SelectedId; }))
	{
		SelectedId.Reset();
	}

	if (Canvas.IsValid())
	{
		Canvas->SetWalls(CanvasWalls);
		Canvas->SetSelectedWall(SelectedId);
	}
	if (WallListView.IsValid())
	{
		WallListView->RequestListRefresh();
		SelectWall(SelectedId);
	}
}

// ------------------------------------------------------------ selection ---

void SWallCorrectionPanel::SelectWall(const FString& Id)
{
	SelectedId = Id;
	if (Canvas.IsValid())
	{
		Canvas->SetSelectedWall(Id);
	}
	if (WallListView.IsValid())
	{
		bSyncingSelection = true;
		if (Id.IsEmpty())
		{
			WallListView->ClearSelection();
		}
		else
		{
			for (const TSharedPtr<FFloorPlanWallItem>& Item : WallItems)
			{
				if (Item->Id == Id)
				{
					WallListView->SetSelection(Item);
					WallListView->RequestScrollIntoView(Item);
					break;
				}
			}
		}
		bSyncingSelection = false;
	}
}

void SWallCorrectionPanel::OnListSelectionChanged(TSharedPtr<FFloorPlanWallItem> Item, ESelectInfo::Type)
{
	if (bSyncingSelection)
	{
		return;
	}
	SelectedId = Item.IsValid() ? Item->Id : FString();
	if (Canvas.IsValid())
	{
		Canvas->SetSelectedWall(SelectedId);
	}
}

void SWallCorrectionPanel::HandleWallPicked(const FString& Id)
{
	SelectWall(Id);
}

void SWallCorrectionPanel::HandleDeleteRequested()
{
	OnRemoveSelectedClicked();
}

// ------------------------------------------------------------- editing ----

FString SWallCorrectionPanel::ThicknessHeightCollisionArgs() const
{
	return FString::Printf(
		TEXT("%f, %f, %s, %s"),
		Context.DefaultThicknessCm,
		Context.WallHeightCm,
		Context.bGenerateCollision ? TEXT("True") : TEXT("False"),
		Context.bCombinedActor ? TEXT("True") : TEXT("False"));
}

void SWallCorrectionPanel::HandleWallDrawn(const FVector2D StartCm, const FVector2D EndCm)
{
	AddWall(StartCm, EndCm);
}

void SWallCorrectionPanel::AddWall(const FVector2D& StartCm, const FVector2D& EndCm)
{
	FString Result;
	const FString Command = FString::Printf(
		TEXT("__import__('floorplan_panel').add_wall_at(%f, %f, %f, %f, %s)"),
		StartCm.X, StartCm.Y, EndCm.X, EndCm.Y, *ThicknessHeightCollisionArgs());
	if (!RunPython(Command, false, FText::GetEmpty(), Result))
	{
		return;
	}

	const FString NewId = FloorPlanPython::UnquoteResult(Result);
	RefreshWalls();
	if (!NewId.IsEmpty())
	{
		SelectWall(NewId);
		StatusText = FText::Format(
			LOCTEXT("StatusAdded", "Added a {0} m wall. Keep drawing, or switch to Select to review."),
			FText::AsNumber(FMath::RoundToFloat(static_cast<float>(FVector2D::Distance(StartCm, EndCm))) / 100.0f));
	}
	else
	{
		StatusText = LOCTEXT("StatusAddFailed", "The wall was not added. See the Output Log.");
	}
}

void SWallCorrectionPanel::RemoveWall(const FString& Id, const FString& Label)
{
	FString Result;
	const FString Command = FString::Printf(
		TEXT("__import__('floorplan_panel').remove_wall(%s)"), *FloorPlanPython::ToPythonLiteral(Id));
	if (RunPython(Command, false, FText::GetEmpty(), Result))
	{
		if (FloorPlanPython::ResultToInt(Result) > 0)
		{
			StatusText = FText::Format(LOCTEXT("StatusRemoved", "Removed {0}."), FText::FromString(Label));
		}
		SelectedId.Reset();
		RefreshWalls();
	}
}

FReply SWallCorrectionPanel::OnAddWallClicked()
{
	if (!Canvas.IsValid())
	{
		return FReply::Handled();
	}
	const FVector2D Centre = Canvas->GetViewCentreCm();
	const FVector2D Half(WallCorrectionPanel::ToolbarWallLengthCm * 0.5f, 0.0);
	AddWall(Centre - Half, Centre + Half);
	return FReply::Handled();
}

FReply SWallCorrectionPanel::OnRemoveSelectedClicked()
{
	if (SelectedId.IsEmpty())
	{
		return FReply::Handled();
	}
	FString Label = SelectedId;
	for (const TSharedPtr<FFloorPlanWallItem>& Item : WallItems)
	{
		if (Item->Id == SelectedId)
		{
			Label = Item->Label;
			break;
		}
	}
	RemoveWall(SelectedId, Label);
	return FReply::Handled();
}

FReply SWallCorrectionPanel::OnRemoveRowClicked(TSharedPtr<FFloorPlanWallItem> Item)
{
	if (Item.IsValid())
	{
		RemoveWall(Item->Id, Item->Label);
	}
	return FReply::Handled();
}

FReply SWallCorrectionPanel::OnSelectInViewportClicked(TSharedPtr<FFloorPlanWallItem> Item)
{
	if (!Item.IsValid())
	{
		return FReply::Handled();
	}
	SelectWall(Item->Id);
	FString Result;
	const FString Command = FString::Printf(
		TEXT("__import__('floorplan_panel').select_wall(%s)"), *FloorPlanPython::ToPythonLiteral(Item->Id));
	if (RunPython(Command, false, FText::GetEmpty(), Result) && FloorPlanPython::ResultToInt(Result) <= 0)
	{
		RefreshWalls();
	}
	return FReply::Handled();
}

FReply SWallCorrectionPanel::OnRefreshClicked()
{
	RefreshWalls();
	StatusText = LOCTEXT("StatusRefreshed", "Re-read the staged walls.");
	return FReply::Handled();
}

FReply SWallCorrectionPanel::OnFitClicked()
{
	if (Canvas.IsValid())
	{
		Canvas->FitToContent();
	}
	return FReply::Handled();
}

FReply SWallCorrectionPanel::OnFinalizeClicked()
{
	FString Result;
	if (!RunPython(
		TEXT("__import__('floorplan_panel').finalize_walls()"),
		true,
		LOCTEXT("Finalizing", "Applying collision and exporting walls_corrected.json..."),
		Result))
	{
		return FReply::Handled();
	}

	TSharedPtr<FJsonValue> Payload;
	const TSharedPtr<FJsonObject>* Summary = nullptr;
	if (!FloorPlanPython::DecodePayload(Result, Payload) || !Payload->TryGetObject(Summary) || !Summary)
	{
		StatusText = LOCTEXT("StatusFinalizeFailed", "Finalize failed. See the Output Log.");
		return FReply::Handled();
	}

	FString StaticMeshPath;
	const bool bBaked = (*Summary)->TryGetStringField(TEXT("static_mesh"), StaticMeshPath) && !StaticMeshPath.IsEmpty();
	const FText BakeText = bBaked
		? FText::Format(LOCTEXT("StatusBaked", " Baked to {0}; the Dynamic Mesh walls were replaced by a Static Mesh Actor."),
			FText::FromString(StaticMeshPath))
		: LOCTEXT("StatusNotBaked", " Static Mesh bake was skipped (see the Output Log).");

	StatusText = FText::Format(
		LOCTEXT("StatusFinalized", "Finalized {0} walls with {1} corrections ({2} removed, {3} added, {4} adjusted). Wrote {5}.{6}"),
		FText::AsNumber(static_cast<int32>((*Summary)->GetNumberField(TEXT("final")))),
		FText::AsNumber(static_cast<int32>((*Summary)->GetNumberField(TEXT("corrections")))),
		FText::AsNumber(static_cast<int32>((*Summary)->GetNumberField(TEXT("removed")))),
		FText::AsNumber(static_cast<int32>((*Summary)->GetNumberField(TEXT("added")))),
		FText::AsNumber(static_cast<int32>((*Summary)->GetNumberField(TEXT("adjusted")))),
		FText::FromString((*Summary)->GetStringField(TEXT("path"))),
		BakeText);
	RefreshWalls();
	return FReply::Handled();
}

// -------------------------------------------------------------- python ----

bool SWallCorrectionPanel::RunPython(const FString& Command, const bool bShowProgress, const FText& ProgressText, FString& OutResult)
{
	bIsRunning = true;
	const FFloorPlanPythonResult Outcome = FloorPlanPython::Exec(Command, bShowProgress, ProgressText);
	bIsRunning = false;

	for (const FFloorPlanPythonLogLine& Line : Outcome.Log)
	{
		switch (Line.Type)
		{
		case EPythonLogOutputType::Error:
			UE_LOG(LogFloorPlanCorrection, Error, TEXT("%s"), *Line.Text);
			break;
		case EPythonLogOutputType::Warning:
			UE_LOG(LogFloorPlanCorrection, Warning, TEXT("%s"), *Line.Text);
			break;
		default:
			UE_LOG(LogFloorPlanCorrection, Log, TEXT("%s"), *Line.Text);
			break;
		}
	}

	OutResult = Outcome.Result;
	if (!Outcome.bPythonAvailable)
	{
		StatusText = FText::FromString(Outcome.Result);
		return false;
	}
	if (!Outcome.bSucceeded)
	{
		StatusText = FText::Format(LOCTEXT("StatusPythonError", "Python error: {0}"), FText::FromString(Outcome.Result));
		return false;
	}
	return true;
}

#undef LOCTEXT_NAMESPACE
