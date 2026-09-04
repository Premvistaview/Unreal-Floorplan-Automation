#include "WallGenerator.h"

#include "Components/DynamicMeshComponent.h"
#include "DynamicMesh/DynamicMesh3.h"
#include "Floor2Dto3Dplan.h"
#include "UDynamicMesh.h"
#include "UObject/UnrealType.h"

using namespace UE::Geometry;

namespace
{
	bool AppendWallBox(FDynamicMesh3& Mesh, const FWallSegment& Segment, const float Height)
	{
		const FVector2D Delta = Segment.End - Segment.Start;
		const double Length = Delta.Length();
		if (Length <= KINDA_SMALL_NUMBER || Segment.Thickness <= KINDA_SMALL_NUMBER || Height <= KINDA_SMALL_NUMBER)
		{
			return false;
		}

		const FVector2D Midpoint = (Segment.Start + Segment.End) * 0.5;
		const double CosAngle = Delta.X / Length;
		const double SinAngle = Delta.Y / Length;
		const double HalfLength = Length * 0.5;
		const double HalfThickness = Segment.Thickness * 0.5;

		const FVector3d LocalPoints[8] =
		{
			{-HalfLength, -HalfThickness, 0.0}, { HalfLength, -HalfThickness, 0.0},
			{ HalfLength,  HalfThickness, 0.0}, {-HalfLength,  HalfThickness, 0.0},
			{-HalfLength, -HalfThickness, Height}, { HalfLength, -HalfThickness, Height},
			{ HalfLength,  HalfThickness, Height}, {-HalfLength,  HalfThickness, Height}
		};

		int32 VertexIDs[8];
		for (int32 Index = 0; Index < 8; ++Index)
		{
			const FVector3d& Local = LocalPoints[Index];
			const FVector3d World(
				Midpoint.X + Local.X * CosAngle - Local.Y * SinAngle,
				Midpoint.Y + Local.X * SinAngle + Local.Y * CosAngle,
				Local.Z
			);
			VertexIDs[Index] = Mesh.AppendVertex(World);
		}

		auto AddTriangle = [&Mesh, &VertexIDs](const int32 A, const int32 B, const int32 C)
		{
			Mesh.AppendTriangle(VertexIDs[A], VertexIDs[B], VertexIDs[C]);
		};

		// Wound so the faces point inward, for viewing the plan from inside the rooms.
		AddTriangle(0, 1, 2); AddTriangle(0, 2, 3);
		AddTriangle(4, 6, 5); AddTriangle(4, 7, 6);
		AddTriangle(0, 5, 1); AddTriangle(0, 4, 5);
		AddTriangle(1, 6, 2); AddTriangle(1, 5, 6);
		AddTriangle(2, 7, 3); AddTriangle(2, 6, 7);
		AddTriangle(3, 4, 0); AddTriangle(3, 7, 4);
		return true;
	}
}

AWallGeneratorActor::AWallGeneratorActor()
{
	PrimaryActorTick.bCanEverTick = false;
	bRunConstructionScriptOnDrag = true;

	DynamicMeshComponent = CreateDefaultSubobject<UDynamicMeshComponent>(TEXT("DynamicMesh"));
	SetRootComponent(DynamicMeshComponent);
	DynamicMeshComponent->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
	DynamicMeshComponent->SetCollisionResponseToAllChannels(ECR_Block);
}

void AWallGeneratorActor::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);
	RebuildMesh();
}

bool AWallGeneratorActor::GenerateWalls(
	const TArray<FWallSegment>& InWallSegments,
	const float InWallHeight,
	const bool bGenerateCollision)
{
	Modify();
	WallSegments = InWallSegments;
	WallHeight = FMath::Max(InWallHeight, 1.0f);

	if (WallSegments.IsEmpty())
	{
		RebuildMesh();
		UE_LOG(LogFloor2Dto3Dplan, Warning, TEXT("GenerateWalls rejected an empty segment array."));
		return false;
	}

	if (!RebuildMesh())
	{
		return false;
	}

	if (bGenerateCollision)
	{
		GenerateCollision();
	}

	return true;
}

bool AWallGeneratorActor::RebuildMesh()
{
	if (!DynamicMeshComponent)
	{
		UE_LOG(LogFloor2Dto3Dplan, Error, TEXT("Wall generation failed: DynamicMeshComponent is null."));
		GeneratedWallCount = 0;
		return false;
	}

	UDynamicMesh* DynamicMesh = DynamicMeshComponent->GetDynamicMesh();
	if (!DynamicMesh)
	{
		UE_LOG(LogFloor2Dto3Dplan, Error, TEXT("Wall generation failed: no UDynamicMesh is available."));
		GeneratedWallCount = 0;
		return false;
	}

	FDynamicMesh3 NewMesh;
	GeneratedWallCount = 0;
	for (int32 Index = 0; Index < WallSegments.Num(); ++Index)
	{
		if (AppendWallBox(NewMesh, WallSegments[Index], WallHeight))
		{
			++GeneratedWallCount;
		}
		else
		{
			UE_LOG(
				LogFloor2Dto3Dplan,
				Warning,
				TEXT("Skipped invalid wall segment %d (zero length, thickness, or height)."),
				Index);
		}
	}

	DynamicMesh->SetMesh(MoveTemp(NewMesh));
	DynamicMeshComponent->NotifyMeshUpdated();

	if (GeneratedWallCount == 0)
	{
		if (WallSegments.IsEmpty())
		{
			UE_LOG(LogFloor2Dto3Dplan, Verbose, TEXT("Wall generator has no segments yet."));
		}
		else
		{
			UE_LOG(
				LogFloor2Dto3Dplan,
				Warning,
				TEXT("Wall generation produced an empty mesh: %d invalid input segment(s), height %.2f cm."),
				WallSegments.Num(),
				WallHeight);
		}
		return false;
	}

	UE_LOG(
		LogFloor2Dto3Dplan,
		Log,
		TEXT("Generated %d wall(s) at height %.2f cm."),
		GeneratedWallCount,
		WallHeight);
	return true;
}

void AWallGeneratorActor::GenerateCollision()
{
	if (DynamicMeshComponent)
	{
		DynamicMeshComponent->EnableComplexAsSimpleCollision();
	}
}

#if WITH_EDITOR
void AWallGeneratorActor::PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent)
{
	Super::PostEditChangeProperty(PropertyChangedEvent);

	auto MatchesWallProperty = [](const FName Name)
	{
		return Name == GET_MEMBER_NAME_CHECKED(AWallGeneratorActor, WallSegments)
			|| Name == GET_MEMBER_NAME_CHECKED(AWallGeneratorActor, WallHeight);
	};

	const bool bRebuild = MatchesWallProperty(PropertyChangedEvent.GetPropertyName())
		|| (PropertyChangedEvent.MemberProperty && MatchesWallProperty(PropertyChangedEvent.MemberProperty->GetFName()));

	if (bRebuild)
	{
		RebuildMesh();
	}
}
#endif
