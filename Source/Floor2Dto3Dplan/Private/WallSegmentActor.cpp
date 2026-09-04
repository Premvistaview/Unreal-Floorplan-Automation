#include "WallSegmentActor.h"

#include "Components/DynamicMeshComponent.h"
#include "DynamicMesh/DynamicMesh3.h"
#include "Floor2Dto3Dplan.h"
#include "UDynamicMesh.h"
#include "UObject/UnrealType.h"

using namespace UE::Geometry;

namespace
{
	bool BuildWallBox(FDynamicMesh3& Mesh, const FVector2D Start, const FVector2D End, const double Thickness, const double Height)
	{
		const FVector2D Delta = End - Start;
		const double Length = Delta.Length();
		if (Length <= KINDA_SMALL_NUMBER || Thickness <= KINDA_SMALL_NUMBER || Height <= KINDA_SMALL_NUMBER)
		{
			return false;
		}

		const FVector2D Midpoint = (Start + End) * 0.5;
		const double CosAngle = Delta.X / Length;
		const double SinAngle = Delta.Y / Length;
		const double HalfLength = Length * 0.5;
		const double HalfThickness = Thickness * 0.5;
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
			VertexIDs[Index] = Mesh.AppendVertex(FVector3d(
				Midpoint.X + Local.X * CosAngle - Local.Y * SinAngle,
				Midpoint.Y + Local.X * SinAngle + Local.Y * CosAngle,
				Local.Z));
		}

		auto AddTriangle = [&Mesh, &VertexIDs](const int32 A, const int32 B, const int32 C)
		{
			Mesh.AppendTriangle(VertexIDs[A], VertexIDs[B], VertexIDs[C]);
		};

		// Match the existing generator's requested inward-facing winding.
		AddTriangle(0, 1, 2); AddTriangle(0, 2, 3);
		AddTriangle(4, 6, 5); AddTriangle(4, 7, 6);
		AddTriangle(0, 5, 1); AddTriangle(0, 4, 5);
		AddTriangle(1, 6, 2); AddTriangle(1, 5, 6);
		AddTriangle(2, 7, 3); AddTriangle(2, 6, 7);
		AddTriangle(3, 4, 0); AddTriangle(3, 7, 4);
		return true;
	}
}

AWallSegmentActor::AWallSegmentActor()
{
	PrimaryActorTick.bCanEverTick = false;
	bRunConstructionScriptOnDrag = true;

	DynamicMeshComponent = CreateDefaultSubobject<UDynamicMeshComponent>(TEXT("DynamicMesh"));
	SetRootComponent(DynamicMeshComponent);
	DynamicMeshComponent->SetCollisionResponseToAllChannels(ECR_Block);
}

void AWallSegmentActor::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);
	RebuildWall();
}

bool AWallSegmentActor::SetWall(
	const FVector2D InStart,
	const FVector2D InEnd,
	const float InThickness,
	const float InHeight,
	const bool bInGenerateCollision)
{
	Modify();
	Start = InStart;
	End = InEnd;
	Thickness = FMath::Max(InThickness, 0.1f);
	Height = FMath::Max(InHeight, 1.0f);
	bGenerateCollision = bInGenerateCollision;
	return RebuildWall();
}

bool AWallSegmentActor::RebuildWall()
{
	if (!DynamicMeshComponent || !DynamicMeshComponent->GetDynamicMesh())
	{
		UE_LOG(LogFloor2Dto3Dplan, Error, TEXT("Wall segment rebuild failed: no Dynamic Mesh is available."));
		return false;
	}

	FDynamicMesh3 NewMesh;
	const bool bBuilt = BuildWallBox(NewMesh, Start, End, Thickness, Height);
	DynamicMeshComponent->GetDynamicMesh()->SetMesh(MoveTemp(NewMesh));
	DynamicMeshComponent->NotifyMeshUpdated();

	if (bGenerateCollision && bBuilt)
	{
		DynamicMeshComponent->SetCollisionEnabled(ECollisionEnabled::QueryAndPhysics);
		DynamicMeshComponent->EnableComplexAsSimpleCollision();
	}
	else
	{
		DynamicMeshComponent->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	}

	if (!bBuilt)
	{
		UE_LOG(
			LogFloor2Dto3Dplan,
			Warning,
			TEXT("%s has an invalid wall (zero length, thickness, or height)."),
			*GetName());
	}
	return bBuilt;
}

#if WITH_EDITOR
void AWallSegmentActor::PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent)
{
	Super::PostEditChangeProperty(PropertyChangedEvent);

	const FName Name = PropertyChangedEvent.GetPropertyName();
	if (Name == GET_MEMBER_NAME_CHECKED(AWallSegmentActor, Start)
		|| Name == GET_MEMBER_NAME_CHECKED(AWallSegmentActor, End)
		|| Name == GET_MEMBER_NAME_CHECKED(AWallSegmentActor, Thickness)
		|| Name == GET_MEMBER_NAME_CHECKED(AWallSegmentActor, Height)
		|| Name == GET_MEMBER_NAME_CHECKED(AWallSegmentActor, bGenerateCollision))
	{
		RebuildWall();
	}
}
#endif
